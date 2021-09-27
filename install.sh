#!/bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'
REBOOT=false
SYSD_LOC=/usr/lib/systemd/system
ENV_FILE=/etc/environment

if [[ -z "${VIZY_HOME}" ]]; then
    PREV_INSTALL=false
    DEFAULT_HOME="${HOME}/vizy"
    echo -en "${YELLOW}Where would you like to install Vizy? (Press ENTER to choose ${DEFAULT_HOME}):${NC}"
    read VIZY_HOME
    VIZY_HOME=${VIZY_HOME:-"${DEFAULT_HOME}"}
    # Clean ENV_FILE of any previous lines
    sudo sed -i '/^VIZY_HOME/d' "${ENV_FILE}"
    echo "VIZY_HOME=${VIZY_HOME}" | sudo tee -a "${ENV_FILE}"
    DEST_DIR="${VIZY_HOME}"

    # Install services
    sudo scripts/install_services

else
    PREV_INSTALL=true
    DEST_DIR="${VIZY_HOME}.new"
fi

# Install any wheels if included 
WHLS="*.whl"
echo "${PWD}"
for f in ${WHLS}; do
    echo -e "\n${GREEN}Installing ${f}...${NC}\n"
    sudo pip3 install --force-reinstall ${f} 
done

# Uninstall vizy
echo -e "\n${GREEN}Uninstalling previous Vizy version...${NC}\n"
sudo pip3 uninstall -y vizy
# Install vizy
echo -e "\n${GREEN}Installing Vizy...${NC}\n"
sudo python3 setup.py install --force
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

if [ "${PREV_INSTALL}" = true ]; then
    # Copy settings in etc directory
    cp -r "${VIZY_HOME}/etc" "${DEST_DIR}"
    # Remove previous backup (we only keep one)
    sudo rm -rf "${VIZY_HOME}.bak"
    # Rename direcories
    mv "${VIZY_HOME}" "${VIZY_HOME}.bak"
    mv "${DEST_DIR}" "${VIZY_HOME}"
    # Change ownership to pi
    sudo chown -R pi "${VIZY_HOME}"
    # Restart vizy software
    # If we're installing via Vizyvisor, this will kill ourselves before 
    # we print a reassuring "success" message (which is important), so we 
    # have an option to skip/defer. 
    if [[ -z "${VIZY_NO_RESTART}" ]]; then
        echo -e "\n${GREEN}Restarting...${NC}"
        sudo service vizy-power-monitor restart
        sudo service vizy-server restart
    fi
else
    echo -en "\n${YELLOW}Reboot required.  Would you like to reboot now? (y or n):${NC}" 
    read -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        REBOOT=true
    fi
fi

if [ "${REBOOT}" = true ]; then
    sudo reboot now
fi