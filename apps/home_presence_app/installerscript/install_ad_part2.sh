
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
echo -e "\e[96m  Installation Part II...\e[90m"
echo -e "\e[0m"

# Preparing Python environment
echo -e "\e[96m[STEP 5/10] Preparing environment...\e[90m"
cd /srv/appdaemon

if python3 -m venv .;
then
    echo -e "\e[32m Environment preparation | Done\e[0m"
else
    echo -e "\e[31m Environment preparation | Failed\e[0m"
    exit;
fi

if source bin/activate;
then
    echo -e "\e[32m[STEP 5/10] Moved to AD and ready for install | Done\e[0m"
else
    echo -e "\e[31m[STEP 5/10] Moved to AD and ready for install | Failed\e[0m"
    exit;
fi


# Install AppDaemon from git
echo -e "\e[96m[STEP 6/10] Installing AppDaemon...\e[90m"
cd /srv/appdaemon

if git clone https://github.com/home-assistant/appdaemon.git;
then
    echo -e "\e[32m Downloading AppDaemon | Done\e[0m"
else
    echo -e "\e[31m Downloading AppDaemon | Failed\e[0m"
    exit;
fi

cd appdaemon

if pip3 install .;
then
    echo -e "\e[32m[STEP 6/10] Installing AppDaemon | Done\e[0m"
else
    echo -e "\e[31m[STEP 6/10] Installing AppDaemon | Failed\e[0m"
    exit;
fi


# Create folders
echo -e "\e[96m[STEP 7/10] Create all needed folders...\e[90m"
mkdir -p /home/appdaemon/.appdaemon/conf/apps
mkdir /home/appdaemon/.appdaemon/conf/apps/home_presence_app
mkdir /home/appdaemon/.appdaemon/log
echo -e "\e[32m[STEP 7/10] Createing folders | Done\e[0m"


# Copy remainig files to correct folders
echo -e "\e[96m[STEP 8/10] Copy configuration files and Monitor-App to AppDaemon...\e[90m"
if cp /home/pi/Monitor-App/apps/home_presence_app/installerscript/appdaemon.yaml /home/appdaemon/.appdaemon/conf/appdaemon.conf;
then
    echo -e "\e[32m Copy configuration files | Done\e[0m"
else
    echo -e "\e[31m Copy configuration files | Failed\e[0m"
    exit;
fi

if cp /home/pi/Monitor-App/apps/home_presence_app/installerscript/apps.yaml /home/appdaemon/.appdaemon/conf/apps/apps.yaml;
then
    echo -e "\e[32m Copy Monitor-App to AppDaemon | Done\e[0m"
else
    echo -e "\e[31m Copy Monitor-App to AppDaemon | Failed\e[0m"
    exit;
fi

if cp /home/pi/Monitor-App/apps/home_presence_app/home_presence_app.py /home/appdaemon/.appdaemon/conf/apps/home_presence_app/home_presence_app.py;
then
    echo -e "\e[32m[STEP 8/10] Copy final files | Done\e[0m"
else
    echo -e "\e[31m[STEP 8/10] Copy final files | Failed\e[0m"
    exit;
fi


# Install Paramiko to be able to reboot external monitors
echo -e "\e[96m[STEP 9/10] Installing Paramiko for remote reboot capabilities...\e[90m"
if pip3 install paramiko;
then
    echo -e "\e[32m[STEP 9/10] Installing Paramiko | Done\e[0m"
else
    echo -e "\e[31m[STEP 9/10] Installing Paramiko | Failed\e[0m"
    exit;
fi

clear
# Final instructions to make the final configurations of
# the files appdaemon.yaml and apps.yaml, templates are already in place
echo -e "\e[0m"
echo -e "\e[96mThe final step now are to fill in information about your own\e[90m"
echo -e "\e[96menvironment, like IP address, username and password ++ for your\e[90m"
echo -e "\e[96mMQTT broker in appdaemon.conf...\e[90m"
echo -e "\e[96mYou will find the file here, and run:\e[90m"
echo -e "\e[32msudo nano /home/appdaemon/.appdaemon/conf/appdaemon.conf\e[0m"
echo -e "\e[96mFinish the edit with ctrl+o & ctrl+x\e[90m"
echo -e "\e[0m"
echo -e "\e[96mThen you need to edit and complete missing information in\e[90m"
echo -e "\e[96mapps.yaml that you will find here, and run:\e[90m"
echo -e "\e[32msudo nano /home/appdaemon/.appdaemon/conf/apps.yaml\e[0m"
echo -e "\e[96mFinish the edit with ctrl+o & ctrl+x\e[90m"
echo -e "\e[0m"
echo -e "\e[96mWhen all that is done, reboot your device.\e[90m"
echo -e "\e[96mIf all went well, you should see new entities in HA\e[90m"
echo -e "\e[0m"
echo -e "\e[96mNow, type \e[32mexit\e[0m and to finalize the installation, you have\e[90m"
echo -e "\e[96m a final command to perform:\e[90m"
echo -e "\e[96mType \e[32msudo systemctl enable appdaemon@appdaemon.service --now\e[0m\e[90m"
echo -e "\e[96mto enable AppDaemon 4.x system service for autostart\e[90m"
echo -e "\e[0m"
echo -e "\e[96mThen what is left is to do \e[32msudo reboot now\e[0m to get going\e[90m"
exit



