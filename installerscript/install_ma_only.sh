
# Bash script to install AppDaemon 4.x to a Raspberry Pi 3/4
# Recommended OS: Latest Raspbian downloaded from raspberrypi.org
# Run: bash -c "$(curl -sL https://raw.githubusercontent.com/Odianosen25/Monitor-App/master/installerscript/install_ad.sh)"
cd ~
clear
echo -e "\e[0m"
echo -e "\e[96m______  ___            __________                    _______                 \e[90m"
echo -e "\e[96m___   |/  /_______________(_)_  /______________      ___    |_______________ \e[90m"
echo -e "\e[96m__  /|_/ /_  __ \_  __ \_  /_  __/  __ \_  ___/________  /| |__  __ \__  __ \ \e[90m"
echo -e "\e[96m_  /  / / / /_/ /  / / /  / / /_ / /_/ /  /   _/_____/  ___ |_  /_/ /_  /_/ / \e[90m"
echo -e "\e[96m/_/  /_/  \____//_/ /_//_/  \__/ \____//_/           /_/  |_|  .___/_  .___/  \e[90m"
echo -e "\e[96m                                                            /_/     /_/    \e[90m"
echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[0m"
cd ~
echo -e "\e[96m  Preparing system for Monitor-App, requires existing installation of AppDaemon 4.x\e[90m"
echo -e "\e[96m  where AppDaemon configuration files are installed to default folder. The script\e[90m"
echo -e "\e[96m  will check this and stop the installation if not.\e[90m"
echo -e "\e[0m"
echo -e "\e[96m  Assuming path to /conf folder: \e[32m/home/appdaemon/.appdaemon/conf\e[96m \e[90m"
echo -e "\e[0m"


# Pre-check to see if conf folder are correct
if cd /home/appdaemon/.appdaemon/conf;
then
    echo -e "\e[32m Checking path to /conf | Done\e[0m"
else
    echo -e "\e[31mChecking path to /conf | Failed\e[0m"
    exit;
 fi

# Returning to user HOME folder
cd ~

# Prepare system
echo -e "\e[96m[STEP 1/6] Updating system...\e[90m"
if sudo apt-get update -y;
then
    echo -e "\e[32m Updating | Done\e[0m"
else
    echo -e "\e[31m Updating | Failed\e[0m"
    exit;
 fi
echo -e "\e[0m"

if sudo apt-get upgrade -y;
then
    echo -e "\e[32m[STEP 1/6] Update & Upgrading | Done\e[0m"
else
    echo -e "\e[31m[STEP 1/6] Update & Upgrading | Failed\e[0m"
    exit;
fi
echo -e "\e[0m"

echo -e "\e[96m[STEP 2/6] Cloning Monitor-App...\e[90m"
if git clone https://github.com/Odianosen25/Monitor-App.git;
then
    echo -e "\e[32m[STEP 2/6] Cloning Monitor-App | Done\e[0m"
else
    echo -e "\e[31m[STEP 2/6] Cloning Monitor-App | Failed\e[0m"
    exit;
fi
echo -e "\e[0m"

# Creating folder for Monitor-App
echo -e "\e[96m[STEP 3/6] Creating folder for Monitor-App...\e[90m"
if sudo mkdir /home/appdaemon/.appdaemon/conf/apps/home_presence_app;
then
    echo -e "\e[32m[STEP 3/6] Creating folder for Monitor-App | Done\e[0m"
else
    echo -e "\e[31m[STEP 3/6] Creating folder for Monitor-App | Failed\e[0m"
    exit;
fi

# Copy remainig files to correct folders
echo -e "\e[96m[STEP 4/6] Copy Monitor-App configuration to AppDaemon...\e[90m"
if cp ~/Monitor-App/installerscript/apps.yaml /home/appdaemon/.appdaemon/conf/apps/home_presence_app.yaml;
then
    echo -e "\e[32m[STEP 4/6] Copy Monitor-App configuration | Done\e[0m"
else
    echo -e "\e[31m[STEP 4/6] Copy Monitor-App configuration | Failed\e[0m"
    exit;
fi

echo -e "\e[96m[STEP 5/6] Copy Monitor-App to AppDaemon...\e[90m"
if cp ~/Monitor-App/apps/home_presence_app/home_presence_app.py /home/appdaemon/.appdaemon/conf/apps/home_presence_app/home_presence_app.py;
then
    echo -e "\e[32m[STEP 5/6] Copy Monitor-App | Done\e[0m"
else
    echo -e "\e[31m[STEP 5/6] Copy Monitor-App | Failed\e[0m"
    exit;
fi


# Install Paramiko to be able to reboot external monitors
echo -e "\e[96m[STEP 6/6] Installing Paramiko for remote reboot capabilities...\e[90m"
if sudo pip3 install paramiko;
then
    echo -e "\e[32m[STEP 6/6] Installing Paramiko | Done\e[0m"
else
    echo -e "\e[31m[STEP 6/6] Installing Paramiko | Failed\e[0m"
    exit;
fi



echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[32mFinally you need to edit and complete missing information in\e[0m"
echo -e "\e[32mhome_presence_app.yaml that you will find here:\e[0m"
echo -e "\e[96msudo nano /home/appdaemon/.appdaemon/conf/home_presence_app.yaml\e[0m"
echo -e "\e[32mFinish the edit with ctrl+o & ctrl+x\e[0m"
echo -e "\e[0m"
echo -e "\e[32mWhen all above is done, \e[96msudo reboot now\e[32m your device.\e[0m"
echo -e "\e[32mIf all went well, you should see new entities in HA\e[0m"
echo -e "\e[0m"
