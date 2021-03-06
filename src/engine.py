import os
from glob import glob
import time
from datetime import datetime

import torch
from torch.optim import lr_scheduler
from utils import Zone, AverageMeter

try:
    from torch.cuda.amp import autocast, GradScaler
except Exception as e:
    print(e)
    pass


class Learner:
    def __init__(self, model, scheduler_class, scheduler_params, hparams):
        self.model = model
        self.hparams = hparams
        self.debug = hparams.debug
        self.root_dir = hparams.root_dir
        self.save_dir = f'{hparams.save_dir}/run_{datetime.now(Zone(+8, False, "GMT")).strftime(f"%Y-%m-%d_%H%M")}'
        self.log_dir = self.save_dir
        self.epoch = 0
        self.best_valid_loss = 1e5
        self.accumulation_steps = hparams.accum_step

        param_optimizer = list(self.model.named_parameters())
        no_decay = ["bias", "LayerNorm.bias", "LayerNorm.weight"]
        optimizer_grouped_parameters = [
            {
                "params": [
                    p for n, p in param_optimizer if not any(nd in n for nd in no_decay)
                ],
                "weight_decay": hparams.wd,
            },
            {
                "params": [
                    p for n, p in param_optimizer if any(nd in n for nd in no_decay)
                ],
                "weight_decay": 0.0,
            },
        ]

        self.optimizer = torch.optim.AdamW(
            optimizer_grouped_parameters, lr=self.hparams.lr
        )
        self.scheduler = scheduler_class(self.optimizer, **scheduler_params)

        self.log(f"{self.hparams}\n", cancel_print=True)

    def fit(self, train_loader, valid_loader):
        if self.hparams.fp16:
            self.scaler = GradScaler()

        for epoch in range(self.hparams.epoch):
            lr = self.optimizer.param_groups[0]["lr"]
            self.log(
                f'\n{datetime.now(Zone(+8, False, "GMT")).strftime(f"%d-%m-%Y %H:%M")}'
            )
            self.log(f"\nEpoch {epoch+1}/{self.hparams.epoch}")
            self.log(f"\nInitial learning rate for epoch {epoch}: {lr:.4e}")

            # Training loop
            t = time.time()
            train_loss = self.train(train_loader)
            tt = time.time() - t
            self.log(
                f"\n[RESULT]: Training loss: {train_loss.avg:.5f}, Time taken: {tt//60:.0f}m {tt%60:.0f}s"
            )
            self.save("last-cp.bin")

            # Validation loop
            t = time.time()
            valid_loss = self.validation(valid_loader)
            tt = time.time() - t
            self.log(
                f"\r\n[RESULT]: Validation loss: {valid_loss.avg:.5f}, Time taken: {tt//60:.0f}m {tt%60:.0f}s"
            )

            if valid_loss.avg < self.best_valid_loss:
                self.best_valid_loss = valid_loss.avg
                self.model.eval()
                self.save(f"ckpt-e{str(epoch).zfill(3)}.bin")
                for path in sorted(glob(f"{self.hparams.root_dir}/ckpt-e*.bin"))[:-3]:
                    os.remove(path)

            if self.hparams.valid_sched:
                self.scheduler.step(metrics=valid_loss.avg)

            if self.debug:
                print("Debug mode: Done training 1 batch and validating 1 epoch.")
                return

            self.epoch += 1

    def train(self, train_loader):
        self.model.train()
        train_loss = AverageMeter()
        t = time.time()
        for step, (images, targets, image_ids) in enumerate(train_loader):
            if self.hparams.verbose:
                if (step + 1) % self.hparams.verbose_step == 0:
                    lr = self.optimizer.param_groups[0]["lr"]
                    print(
                        f"\rTraining step {step+1}/{len(train_loader)}, "
                        + f"Learning rate {lr:.4e}, "
                        + f"Training loss: {train_loss.avg:.5f}, "
                        + f"Time taken: {(time.time() - t):.1f}s",
                        end="",
                    )

            images = torch.stack(images).to("cuda").float()
            boxes = [target["boxes"].to("cuda").float() for target in targets]
            labels = [target["labels"].to("cuda").float() for target in targets]

            if self.hparams.fp16:
                with autocast():
                    loss, _, _ = self.model(images, boxes, labels)
            else:
                loss, _, _ = self.model(images, boxes, labels)

            loss /= self.accumulation_steps

            if (step + 1) % self.accumulation_steps == 0:
                if self.hparams.fp16:
                    self.scaler.scale(loss).backward()
                    self.scaler.step(self.optimizer)
                    self.scaler.update()
                    # self.scaler.unscale_(self.optimizer)
                else:
                    loss.backward()
                    self.optimizer.step()

                self.optimizer.zero_grad()

            if self.hparams.step_sched:
                self.scheduler.step()

            batch_size = images.shape[0]
            train_loss.update(
                loss.detach().item() * self.accumulation_steps, batch_size
            )

            if self.debug:
                self.save("last-cp.bin")
                break

        return train_loss

    def validation(self, val_loader):
        self.model.eval()
        valid_loss = AverageMeter()
        t = time.time()
        for step, (images, targets, image_ids) in enumerate(val_loader):

            if self.hparams.verbose:
                if step % self.hparams.verbose_step == 0:
                    print(
                        f"\rValidation step {step+1}/{len(val_loader)}, "
                        + f"Validation loss: {valid_loss.avg:.5f}, "
                        + f"Time taken: {(time.time() - t):.1f}s",
                        end="",
                    )

            # all_predictions = []
            with torch.no_grad():
                images = torch.stack(images).to("cuda").float()
                boxes = [target["boxes"].to("cuda").float() for target in targets]
                labels = [target["labels"].to("cuda").float() for target in targets]
                # print(boxes[0])

                loss, _, _ = self.model(images, boxes, labels)
                batch_size = images.shape[0]
                valid_loss.update(loss.detach().item(), batch_size)

                # Calculate metric (mAP)

                # preds = eval_model(images, torch.tensor([1]*images.shape[0]).float().cuda())
                # evaluate_MAP(preds, targets, bs=images.shape[0], all_predictions=all_predictions)

        return valid_loss

    def save(self, name):

        self.model.eval()
        torch.save(
            {
                "model_state_dict": self.model.model.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "scheduler_state_dict": self.scheduler.state_dict(),
                "best_valid_loss": self.best_valid_loss,
                "epoch": self.epoch,
            },
            os.path.join(self.save_dir, name),
        )

    def load(self, path, weights_only):

        checkpoint = torch.load(path)
        self.model.model.load_state_dict(checkpoint["model_state_dict"])

        if not weights_only:
            self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
            self.scheduler.load_state_dict(checkpoint["scheduler_state_dict"])
            self.best_valid_loss = checkpoint["best_valid_loss"]
            self.epoch = checkpoint["epoch"] + 1

    def log(self, message, cancel_print=False):

        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        if self.hparams.verbose and not cancel_print:
            print(message)

        with open(f"{self.log_dir}/log.txt", "a+") as logger:
            logger.write(f"{message}\n")


def get_scheduler(hparams: dict):

    if hparams.scheduler == "plateau":
        scheduler_class = lr_scheduler.ReduceLROnPlateau
        scheduler_params = dict(
            mode=hparams.valid_sched_metric,
            factor=hparams.lr_reduce_factor,
            patience=hparams.patience,
            verbose=hparams.sched_verbose,
            threshold=1e-4,
            threshold_mode="abs",
            cooldown=0,
            min_lr=1e-8,
            eps=1e-08,
        )
        hparams.valid_sched = True
        hparams.step_sched = False

    elif hparams.scheduler == "one_cycle":
        scheduler_class = lr_scheduler.OneCycleLR
        scheduler_params = dict(
            max_lr=hparams.lr,
            epochs=hparams.epoch,
            steps_per_epoch=hparams.steps_per_epoch,
            pct_start=hparams.pct_start,
            anneal_strategy="cos",
            cycle_momentum=True,
            div_factor=hparams.div_factor,
        )
        hparams.step_sched = True
        hparams.valid_sched = False

    return scheduler_class, scheduler_params
