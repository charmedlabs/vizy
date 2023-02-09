#!/bin/bash

# Exit on error
set -e

VERSION=0.0.0

if [[ $EUID -ne 0 ]]; then
   sudo bash `realpath "$0"`
   exit 
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'
REBOOT=false
SYSD_LOC=/usr/lib/systemd/system
ENV_FILE=/etc/environment
REBOOT=false 

limits_conf() {
  local LINE1='pi hard rtprio 99'
  local LINE2='pi soft rtprio 99'
  local FILE='/etc/security/limits.conf'
  grep -qF -- "$LINE1" $FILE || { echo "$LINE1" >> $FILE; REBOOT=true; }
  grep -qF -- "$LINE2" $FILE || { echo "$LINE2" >> $FILE; REBOOT=true; }
}

echo -e "${GREEN}Installing Vizy version ${VERSION}...${NC}"

if [[ -z "${VIZY_HOME}" ]]; then
    eval `cat /etc/environment` 
    if [[ -z "${VIZY_HOME}" ]]; then
        PREV_INSTALL=false
        REBOOT=true
        DEFAULT_HOME="${HOME}/vizy"
        echo -en "${YELLOW}Where would you like to install Vizy? (Press ENTER to choose ${DEFAULT_HOME}):${NC}"
        read VIZY_HOME
        VIZY_HOME=${VIZY_HOME:-"${DEFAULT_HOME}"}
        # Clean ENV_FILE of any previous lines
        sed -i '/^VIZY_HOME/d' "${ENV_FILE}"
        echo "VIZY_HOME=${VIZY_HOME}" >> "${ENV_FILE}"
        DEST_DIR="${VIZY_HOME}"
    fi
fi
if [[ -n "${VIZY_HOME}" ]]; then
    PREV_INSTALL=true
    DEST_DIR="${VIZY_HOME}.new"
fi

# Update firmware if necessary
echo -e "\n${GREEN}Checking power firmware...${NC}\n"
scripts/update_power_firmware
# Check/install services
if ! scripts/install_services; then
    REBOOT=true
fi
# Change limits.conf file if necessary
limits_conf

# Install system packages
echo -e "\n${GREEN}Installing system packages...${NC}\n"
apt-get -y install libportaudio2 
apt-get -y install zip unzip

# Upgrade pip
echo -e "\n${GREEN}Upgrading pip...${NC}\n"
python3 -m pip install --upgrade pip

# Install this pre-compiled version of numpy before we install tensorflow
echo -e "\n${GREEN}Installing numpy 1.21.6...${NC}\n"
python3 -m pip install numpy-1.21.6-cp37-cp37m-linux_armv7l.whl --root-user-action=ignore --no-warn-conflicts

# Install any packages that aren't included in the original image
echo -e "\n${GREEN}Installing aiohttp 3.8.1...${NC}\n"
python3 -m pip install aiohttp==3.8.1 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing numexpr 2.7.0...${NC}\n"
python3 -m pip install numexpr==2.7.0 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing gspread-dataframe 3.3.0...${NC}\n"
python3 -m pip install gspread-dataframe==3.3.0 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing cachetools 5.2.0...${NC}\n"
python3 -m pip install cachetools==5.2.0 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing google-auth 2.12.0...${NC}\n"
python3 -m pip install google-auth==2.12.0 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing python-telegram-bot 20.0.a4...${NC}\n"
python3 -m pip install python-telegram-bot==20.0.a4 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing opencv-python 4.5.3.56...${NC}\n"
python3 -m pip install opencv-python==4.5.3.56 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing tflite-runtime 2.7.0...${NC}\n"
python3 -m pip install tflite-runtime==2.7.0 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing tflite-support 0.4.0...${NC}\n"
python3 -m pip install tflite-support==0.4.0 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing openpyxl 3.0.10...${NC}\n"
python3 -m pip install openpyxl==3.0.10 --root-user-action=ignore --no-warn-conflicts
echo -e "\n${GREEN}Installing gdown 4.6.0...${NC}\n"
python3 -m pip install gdown==4.6.0 --root-user-action=ignore --no-warn-conflicts

# Install any wheels if included.  Do this AFTER we install the packages because if any 
# of the packages fail to install, we don't want a new version of Kritter (which is installed
# as a wheel) to reference non-existent packages.
WHLS="*.whl"
echo "${PWD}"
for f in ${WHLS}; do
    # exclude numpy since we've already installed it
    if [ ${f} != "numpy-1.21.6-cp37-cp37m-linux_armv7l.whl" ]
    then
        echo -e "\n${GREEN}Installing ${f}...${NC}\n"
        python3 -m pip install --force-reinstall ${f} --root-user-action=ignore --no-warn-conflicts
    fi
done

# Update dash_renderer version so browsers load the new version
DR_INIT_FILE="/usr/local/lib/python3.7/dist-packages/dash_renderer/__init__.py"
DR_NEW_VER="1.9.2"
DR_OLD_VER=`grep -oP '(?<=version__ = ").*?(?=")' <<< "$s" ${DR_INIT_FILE}`
sed -i 's/"'${DR_OLD_VER}'"/"'${DR_NEW_VER}'"/g' ${DR_INIT_FILE}

# Uninstall vizy
echo -e "\n${GREEN}Uninstalling previous Vizy version...${NC}\n"
python3 -m pip uninstall -y vizy --root-user-action=ignore
# Install vizy
echo -e "\n${GREEN}Installing Vizy...${NC}\n"
python3 setup.py install --force
# Copy to final destination
echo -e "\n${GREEN}Copying...${NC}"
mkdir -p "${DEST_DIR}"
if [ -d apps ]; then
    cp -r apps "${DEST_DIR}"
fi
if [ -d examples ]; then
    cp -r examples "${DEST_DIR}"
fi
if [ -d scripts ]; then
    cp -r scripts "${DEST_DIR}"
fi
if [ -d sys ]; then
    cp -r sys "${DEST_DIR}"
fi

if ${PREV_INSTALL}; then
    # Move settings and projects in etc directory
    mv "${VIZY_HOME}/etc" "${DEST_DIR}"
    # Remove previous backup (we only keep one)
    rm -rf "${VIZY_HOME}.bak"
    # Rename direcories
    mv "${VIZY_HOME}" "${VIZY_HOME}.bak"
    mv "${DEST_DIR}" "${VIZY_HOME}"
fi

# Change ownership to pi
chown -R pi "${VIZY_HOME}"

if ${REBOOT}; then
    echo -en "\n${YELLOW}Reboot required.  Would you like to reboot now? (y or n):${NC}" 
    read -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        reboot now
    fi
elif ${PREV_INSTALL}; then
    # Restart vizy software
    # If we're installing via Vizyvisor, this will kill ourselves before 
    # we print a reassuring "success" message (which is important), so we 
    # have an option to skip/defer. 
    if [[ -z "${VIZY_NO_RESTART}" ]]; then
        echo -e "\n${GREEN}Restarting...${NC}"
        service vizy-power-monitor restart
        service vizy-server restart
    fi
fi
