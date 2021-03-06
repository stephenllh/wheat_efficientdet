import numpy as np
import numba
from numba import jit


@jit(nopython=True)
def calculate_iou(gt, pr, form="pascal_voc") -> float:

    """Calculates the Intersection over Union.

    Args:
        gt: (np.ndarray[Union[int, float]]) coordinates of the ground-truth box
        pr: (np.ndarray[Union[int, float]]) coordinates of the predicted box
        form: (str) gt/pred coordinates format
            - pascal_voc: [xmin, ymin, xmax, ymax]
            - coco: [xmin, ymin, w, h]
    Returns:
        (float) Intersection over union (0.0 <= iou <= 1.0)
    """

    if form == "coco":
        gt = gt.copy()
        pr = pr.copy()

        gt[2] = gt[0] + gt[2]
        gt[3] = gt[1] + gt[3]
        pr[2] = pr[0] + pr[2]
        pr[3] = pr[1] + pr[3]

    # Calculate overlap area
    dx = min(gt[2], pr[2]) - max(gt[0], pr[0]) + 1

    if dx < 0:
        return 0.0

    dy = min(gt[3], pr[3]) - max(gt[1], pr[1]) + 1

    if dy < 0:
        return 0.0

    overlap_area = dx * dy

    # Calculate union area
    union_area = (
        (gt[2] - gt[0] + 1) * (gt[3] - gt[1] + 1)
        + (pr[2] - pr[0] + 1) * (pr[3] - pr[1] + 1)
        - overlap_area
    )

    return overlap_area / union_area


@jit(nopython=True)
def find_best_match(
    gts, pred, pred_idx, threshold=0.5, form="pascal_voc", ious=None
) -> int:

    """
    Returns the index of the 'best match' between the ground-truth boxes and the prediction.
    The 'best match' is the highest IoU. (0.0 IoUs are ignored).

    Args:
        gts: (List[List[Union[int, float]]]) Coordinates of the available ground-truth boxes
        pred: (List[Union[int, float]]) Coordinates of the predicted box
        pred_idx: (int) Index of the current predicted box
        threshold: (float) Threshold
        form: (str) Format of the coordinates
        ious: (np.ndarray) len(gts) x len(preds) matrix for storing calculated ious.

    Return:
        (int) Index of the best match GT box (-1 if no match above threshold)
    """

    best_match_iou = -np.inf
    best_match_idx = -1

    for gt_idx in range(len(gts)):

        if gts[gt_idx][0] < 0:
            # Already matched GT-box
            continue

        iou = -1 if ious is None else ious[gt_idx][pred_idx]

        if iou < 0:
            iou = calculate_iou(gts[gt_idx], pred, form=form)

            if ious is not None:
                ious[gt_idx][pred_idx] = iou

        if iou < threshold:
            continue

        if iou > best_match_iou:
            best_match_iou = iou
            best_match_idx = gt_idx

    return best_match_idx


@jit(nopython=True)
def calculate_precision(gts, preds, threshold=0.5, form="coco", ious=None) -> float:
    """
    Calculates precision for ground truth-prediction pairs at a particular threshold.

    Args:
        gts (List[List[Union[int, float]]]): Coordinates of the available ground-truth boxes
        preds (List[List[Union[int, float]]]): Coordinates of the predicted boxes, sorted by descending confidence value
        threshold (float): Threshold
        form (str): Format of the coordinates
        ious (np.ndarray): len(gts) x len(preds) matrix for storing calculated ious.

    Return:
        precision (float)
    """

    tp = 0
    fp = 0

    for pred_idx in range(len(preds)):
        best_match_gt_idx = find_best_match(
            gts, preds[pred_idx], pred_idx, threshold=threshold, form=form, ious=ious
        )

        if best_match_gt_idx >= 0:
            tp += 1  # True positive: The predicted box matches a gt box with an IoU above the threshold.
            gts[best_match_gt_idx] = -1  # Remove the matched GT box

        else:  # No match
            fp += (
                1  # False positive: indicates a predicted box had no associated gt box.
            )

    # False negative: indicates a gt box had no associated predicted box.
    fn = (gts.sum(axis=1) > 0).sum()

    return tp / (tp + fp + fn)


@jit(nopython=True)
def calculate_image_precision(gts, preds, thresholds=(0.5,), form="coco") -> float:
    """
    Calculates image precision.

    Args:
        gts: (List[List[Union[int, float]]]) Coordinates of the available ground-truth boxes
        preds: (List[List[Union[int, float]]]) Coordinates of the predicted boxes, sorted by descending confidence value
        thresholds: (float) Different thresholds
        form: (str) Format of the coordinates

    Return:
        (float) Precision
    """

    image_precision = 0.0
    ious = np.ones((len(gts), len(preds))) * -1

    for threshold in thresholds:
        precision_at_threshold = calculate_precision(
            gts.copy(), preds, threshold=threshold, form=form, ious=ious
        )
        image_precision += precision_at_threshold / len(thresholds)

    return image_precision


def calculate_final_score(all_predictions, score_threshold):

    final_scores = []

    for i in range(len(all_predictions)):
        gt_boxes = all_predictions[i]["gt_boxes"].copy()
        pred_boxes = all_predictions[i]["pred_boxes"].copy()
        scores = all_predictions[i][
            "scores"
        ].copy()  # confidence levels of predicted bounding boxes
        # image_id = all_predictions[i]["image_id"]

        indexes = np.where(scores > score_threshold)
        pred_boxes = pred_boxes[indexes]
        scores = scores[indexes]

        iou_thresholds = numba.typed.List()
        thresholds = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75]
        for x in thresholds:  # these thresholds are for this competition only!
            iou_thresholds.append(x)

        image_precision = calculate_image_precision(
            gt_boxes, pred_boxes, thresholds=iou_thresholds, form="pascal_voc"
        )
        final_scores.append(image_precision)

    return np.mean(final_scores)


def evaluate_MAP(preds, targets, bs, all_predictions):
    for i in range(bs):
        boxes = preds[i].detach().cpu().numpy()[:, :4]
        scores = preds[i].detach().cpu().numpy()[:, 4]
        boxes[:, 2] = boxes[:, 2] + boxes[:, 0]
        boxes[:, 3] = boxes[:, 3] + boxes[:, 1]
        targets[i]["boxes"][:, [0, 1, 2, 3]] = targets[i]["boxes"][
            :, [1, 0, 3, 2]
        ]  # convert back target boxes to xyxy

        all_predictions.append(
            {
                "pred_boxes": (boxes * 2)
                .clip(min=0, max=1023)
                .astype(
                    int
                ),  # multiply by 2 because we need to convert size 512 to 1024. (differs with competitions)
                "scores": scores,
                "gt_boxes": (targets[i]["boxes"].cpu().numpy() * 2)
                .clip(min=0, max=1023)
                .astype(int),
                # "image_id": image_ids[i],
            }
        )

    best_final_score = 0
    # best_score_threshold = 0
    for score_threshold in np.arange(0.2, 0.5, 0.01):
        final_score = calculate_final_score(all_predictions, score_threshold)
        if final_score > best_final_score:
            best_final_score = final_score
            # best_score_threshold = score_threshold

    return best_final_score
