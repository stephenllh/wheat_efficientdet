import numpy as np
from sklearn.model_selection import StratifiedKFold


def process_data(df, subset=1.0):
    bboxes = np.stack(df["bbox"].apply(lambda x: np.fromstring(x[1:-1], sep=",")))

    for i, column in enumerate(["x", "y", "w", "h"]):
        df[column] = bboxes[:, i]

    df = df.drop(columns=["bbox"])
    df = df.sample(frac=subset).reset_index(drop=True)

    return df


def create_folds(df, n_folds):
    df_folds = df[["image_id"]].copy()

    # Group the dataframe by image_id (because 1 image_id can appear in multiple rows) and get the bbox_count
    df_folds.loc[:, "bbox_count"] = 1  # each row corresponds to 1 bbox
    df_folds = df_folds.groupby("image_id").count()

    # Match the source to each image_id
    df_folds["source"] = (
        df[["image_id", "source"]].groupby("image_id").first()["source"]
    )  # besides first(), min() or max() achieves the same

    # Create stratify group
    df_folds["stratify_group"] = np.char.add(
        df_folds["source"].values.astype(str),
        df_folds["bbox_count"]
        .apply(lambda x: f"_{x//15}")
        .values.astype(str),  # 15 is rather arbritrary
    )

    # Initialize fold as -1
    df_folds["fold"] = -1

    # Assign fold indices
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    for fold_idx, (train_idx, valid_idx) in enumerate(
        skf.split(X=df_folds.index, y=df_folds["stratify_group"])
    ):
        df_folds.loc[df_folds.iloc[valid_idx].index, "fold"] = fold_idx

    return df_folds
