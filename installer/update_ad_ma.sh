# Bash script to update both AppDaemon 4.x and Monitor-App to latest version
# Recommended OS: Latest Raspbian downloaded from raspberrypi.org
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
echo -e "\e[32m  Preparing system for \e[96mupdating\e[32m of both AppDaemon 4.x & Monitor-App...\e[0m"
echo -e "\e[0m"

# Prepare system
echo -e "\e[96m[STEP 1/10] Updating system...\e[90m"
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
    echo -e "\e[32m[STEP 1/10] Update & Upgrading | Done\e[0m"
else
    echo -e "\e[31m[STEP 1/10] Update & Upgrading | Failed\e[0m"
    exit;
fi
echo -e "\e[0m"

cd ~/Monitor-App

if git pull;
then
    echo -e "\e[32m[STEP 2/10] Downloading latest Monitor-App | Done\e[0m"
else
    echo -e "\e[31m[STEP 2/10] Downloading latest Monitor-App | Failed\e[0m"
    exit;
fi
echo -e "\e[0m"

# Replacing old with new version of Monitor-App within AppDaemon
sudo rm /home/appdaemon/.appdaemon/conf/apps/home_precense_app/home_precense_app.py
sudo cp ~/Monitor-App/apps/home_precense_app/home_precense_app.py /appdaemon/.appdaemon/conf/apps/home_precense_app/home_precense_app.py


# Prepare ipdate part 2 file
if sudo cp ~/Monitor-App/installerscript/update_ad_ma_part2.sh ~/update_ad_ma_part2.sh;
then
    echo -e "\e[32mPreparation of update part 2 | Done\e[0m"
else
    echo -e "\e[31mPreparation of update part 2 | Failed\e[0m"
    exit;
fi

if sudo chmod +x ~/update_ad_ma_part2.sh;
then
    echo -e "\e[32mDone\e[0m"
else
    echo -e "\e[31mFailed\e[0m"
    exit;
fi

echo " "
echo " "
echo " "
echo -e "\e[32mTo continue installation, type: \e[96mbash update_ad_ma_part2.sh\e[0m"
echo " "
echo " "
echo " "

if sudo -u appdaemon -H -s;
then
    echo -e " "
else
    echo -e " "
    exit;
fi


#####################################################################3
# Here, 'update_ad_ma_part2.sh' are running
######################################################################


if sudo systemctl restart appdaemon@appdaemon.service --now;
then
    echo -e "\e[32mAppDaemon Running again | Done\e[0m"
else
    echo -e "\e[31mAppDaemon Running again | Failed\e[0m"
    exit;
fi

echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[32mIf all went well, both Monitor-App and AppDaemon are now\e[0m"
echo -e "\e[32mupdated to latest build. Both has been restarted successfully.\e[0m"
echo -e "\e[0m"
echo -e "\e[0m"