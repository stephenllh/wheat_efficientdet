pip install -U -q albumentations
pip install -q timm
pip install -q omegaconf
pip install -q --upgrade --force-reinstall --no-deps kaggle
pip install torch==1.6.0+cu101 torchvision==0.7.0+cu101 -f https://download.pytorch.org/whl/torch_stable.html

mkdir wheat_efficientdet/input
unzip -q 'drive/My Drive/DL/kaggle/global_wheat_detection/data.zip' -d 'wheat_efficientdet/input'

kaggle datasets download -d mathurinache/efficientdet
mkdir wheat_efficientdet/pretrained_models
unzip -q efficientdet.zip -d wheat_efficientdet/pretrained_models

cd wheat_efficientdet/src