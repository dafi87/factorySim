#!/bin/bash

# Update packages
apt update

# Non-interactive mode, use default answers
export DEBIAN_FRONTEND=noninteractive

# Workaround for libc6 bug - asking about service restart in non-interactive mode
# https://bugs.launchpad.net/ubuntu/+source/eglibc/+bug/935681
echo 'libc6 libraries/restart-without-asking boolean true' | debconf-set-selections

# Install curl
apt install -y curl 

# Install Python 3.7
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt -y install python3.7 python3.7-dev
curl https://bootstrap.pypa.io/get-pip.py | sudo python3.7

# Add NVIDIA package repositories
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/cuda-repo-ubuntu1804_10.1.243-1_amd64.deb
apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/7fa2af80.pub
dpkg -i cuda-repo-ubuntu1804_10.1.243-1_amd64.deb
apt update
wget http://developer.download.nvidia.com/compute/machine-learning/repos/ubuntu1804/x86_64/nvidia-machine-learning-repo-ubuntu1804_1.0.0-1_amd64.deb
apt install ./nvidia-machine-learning-repo-ubuntu1804_1.0.0-1_amd64.deb

# Install NVIDIA driver
apt install -y --no-install-recommends nvidia-driver-430
# Reboot. Check that GPUs are visible using the command: nvidia-smi

# Install development and runtime libraries (~4GB)
apt install -y --no-install-recommends \
    cuda-10-1 \
    libcudnn7=7.6.4.38-1+cuda10.1  \
    libcudnn7-dev=7.6.4.38-1+cuda10.1

# Install TensorRT. Requires that libcudnn7 is installed above.
apt install -y --no-install-recommends libnvinfer6=6.0.1-1+cuda10.1 \
    libnvinfer-dev=6.0.1-1+cuda10.1 \
    libnvinfer-plugin6=6.0.1-1+cuda10.1

#Add executables to Path
export PATH=/usr/local/cuda-10.2/bin:/usr/local/cuda-10.2/NsightCompute-2019.1${PATH:+:${PATH}}

# Install ffmpeg
apt install -y ffmpeg 

# Install cairo for pycairo
apt install -y libcairo2

# Install PyTorch
#pip3.7 install $(curl https://pytorch.org/assets/quick-start-module.js | grep -A1 "stable,pip,linux,cuda10.0,python3.7" | grep -oP 'https.*?\.whl')
pip3.7 install torch torchvision

# Install other Python packages
pip3.7 install -r requirements.txt

#Download OpenAi Gym
git clone https://github.com/openai/gym 
cd gym/
pip3.7 install -e .
cd ..

#Install current Version of factorySim into Gym
cd factory_env/
pip3.7 install -e .
cd ..

#Install ifcopenshell
mkdir -p `python3.7 -m site --user-site`
cd `python3.7 -m site --user-site`
curl -sS https://s3.amazonaws.com/ifcopenshell-builds/ifcopenshell-python-37-v0.6.0-e44221c-linux64.zip > file.zip 
unzip file.zip                                  
rm file.zip

# Reboot
reboot