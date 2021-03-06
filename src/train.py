import os
import warnings
import pandas as pd
import argparse
from data import process_data, create_folds
from dataloader import get_train_loader, get_valid_loader
from transforms import get_train_augs, get_valid_augs
from model import get_model
from engine import get_scheduler, Learner
from utils import seed_everything

warnings.simplefilter(action="ignore", category=FutureWarning)


parser = argparse.ArgumentParser(description="Wheat detection with EfficientDet")

# Directories
parser.add_argument("--root-dir", default="../", type=str, help="directory of root")
parser.add_argument("--data-dir", default="../input", type=str, help="data directory")
parser.add_argument(
    "--model-dir",
    default="../pretrained_models",
    type=str,
    help="directory of downloaded efficientnet models",
)
parser.add_argument(
    "--save-dir", default="../models", type=str, help="saved model directory"
)

# Training fold
parser.add_argument("--n-folds", default=5, type=int, help="number of k-folds")
parser.add_argument("--subset", default=1.0, type=float, help="subset of data")
parser.add_argument("--fold", default=0, type=int, help="fold number")

# Augmentations
parser.add_argument("--crop", default=0.5, type=float, help="random sized crop prob")
parser.add_argument("--hue", default=0.9, type=float, help="proba of hue saturation")
parser.add_argument(
    "--bright-contrast",
    default=0.9,
    type=float,
    help="proba of RandomBrightnessContrast",
)
parser.add_argument(
    "--gray", default=0.01, type=float, help="proba of converting to grayscale"
)
parser.add_argument("--hflip", default=0.5, type=float, help="proba of horizontal flip")
parser.add_argument("--vflip", default=0.5, type=float, help="proba of vertical flip")
parser.add_argument("--img-size", default=512, type=int, help="image size")
parser.add_argument("--cut-holes", default=8, type=int, help="no. of holes in cutout")
parser.add_argument("--cutout", default=0.5, type=float, help="proba of cutout")
parser.add_argument("--cutmix", default=True, type=bool, help="do cutmix or not")

# Model variant selection
parser.add_argument(
    "--model-variant", "-m", required=True, type=str, help="model variant: d0 to d7"
)

# Training
parser.add_argument("--epoch", "-e", type=int, required=True, help="number of epochs")
parser.add_argument("--lr", default=2e-4, type=float, help="(max) learning rate")
parser.add_argument("--bs", default=4, type=int, help="batch size")
parser.add_argument("--accum-step", default=1, type=int, help="no. accumulation steps")
parser.add_argument("--wd", default=1e-3, type=float, help="weight decay")
parser.add_argument("--num-workers", default=4, type=int, help="num workers")
parser.add_argument("--fp16", default=False, action="store_true")

# Scheduler
parser.add_argument(
    "--scheduler",
    default="plateau",
    type=str,
    help='scheduler class: choose from ["plateau", "one_cycle"]',
)
parser.add_argument(
    "--sched-verbose", default=True, type=bool, help="scheduler verbosity"
)
parser.add_argument("--verbose", default=True, type=bool, help="Learner verbosity")
parser.add_argument(
    "--verbose-step", default=1, type=int, help="Learner verbosity step"
)
parser.add_argument("--debug", default=False, type=bool, help="debug mode in Learner")

# Scheduler args: ReduceLROnPlateau
parser.add_argument(
    "--valid-sched-metric",
    default="min",
    type=str,
    help="the mode argument in valid scheduler",
)
parser.add_argument(
    "--lr-reduce-factor",
    default=0.5,
    type=float,
    help="reduce factor in ReduceLROnPlateau",
)
parser.add_argument("--patience", default=2, type=int, help="patience of val scheduler")

# Scheduler args: OneCycle
parser.add_argument(
    "--pct_start",
    default=0.3,
    type=float,
    help="pct of total no. iterations to start annealing",
)
parser.add_argument(
    "--div_factor", default=10, type=int, help="lr reduction factor at beginning"
)

# Seed
parser.add_argument("--seed", default=42, type=int, help="seed")

# Save model
parser.add_argument("--save-name", default="model", type=str, help="saved model name")

# Load model
parser.add_argument(
    "--load-path", default="", type=str, help="dir + name of loaded model"
)
parser.add_argument(
    "--weights-only",
    default=True,
    type=bool,
    help="True: use as transfer learning. False: continue from checkpoint.",
)


args = parser.parse_args()


def run():
    seed_everything(args.seed)

    df = pd.read_csv(os.path.join(args.data_dir, "train.csv"))
    df = process_data(df, args.subset)
    df_folds = create_folds(df, args.n_folds)

    train_image_ids = df_folds[df_folds["fold"] != args.fold].index.values
    valid_image_ids = df_folds[df_folds["fold"] == args.fold].index.values

    train_loader = get_train_loader(
        args.data_dir,
        df,
        train_image_ids,
        transforms=get_train_augs(args),
        do_cutmix=args.cutmix,
        batch_size=args.bs,
        num_workers=args.num_workers,
    )

    valid_loader = get_valid_loader(
        args.data_dir,
        df,
        valid_image_ids,
        transforms=get_valid_augs(args),
        batch_size=args.bs,
        num_workers=args.num_workers,
    )

    model = get_model(
        args.model_variant, model_dir=args.model_dir, checkpoint_path=args.load_path
    ).cuda()

    if args.scheduler == "one_cycle":
        args.steps_per_epoch = len(train_image_ids) // args.bs
        scheduler_class, scheduler_params = get_scheduler(args)

    else:
        scheduler_class, scheduler_params = get_scheduler(args)

    learner = Learner(model, scheduler_class, scheduler_params, hparams=args)
    learner.fit(train_loader, valid_loader)


if __name__ == "__main__":
    run()
