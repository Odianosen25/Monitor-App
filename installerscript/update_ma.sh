
# Bash script to update Monitor-App 
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
echo -e "\e[96m  Preparing update for Monitor-App, requires existing installation of AppDaemon 4.x\e[90m"
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
if cd ~/Monitor-App;
then
    echo -e "\e[32m\e[0m"
else
    echo -e "\e[31mMonitor-App repo not cloned | Failed\e[0m"
    exit;
 fi

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

echo -e "\e[96m[STEP 2/6] updating Monitor-App from Git...\e[90m"
if git pull;
then
    echo -e "\e[32m[STEP 2/6] Update Monitor-App | Done\e[0m"
else
    echo -e "\e[31m[STEP 2/6] Update Monitor-App | Failed\e[0m"
    exit;
fi
echo -e "\e[0m"

# Deleting existing version of Monitor-App
echo -e "\e[96m[STEP 3/6] Deleting existing version of Monitor-App...\e[90m"
if sudo rm /home/appdaemon/.appdaemon/conf/apps/home_presence_app/home_presence_app.py;
then
    echo -e "\e[32m[STEP 3/6] Deleting Monitor-App | Done\e[0m"
else
    echo -e "\e[31m[STEP 3/6] Deleting folder for Monitor-App | Failed\e[0m"
    exit;
fi


echo -e "\e[96m[STEP 4/6] Copy Monitor-App to AppDaemon...\e[90m"
if cp ~/Monitor-App/apps/home_presence_app/home_presence_app.py /home/appdaemon/.appdaemon/conf/apps/home_presence_app/home_presence_app.py;
then
    echo -e "\e[32m[STEP 4/6] Copy Monitor-App | Done\e[0m"
else
    echo -e "\e[31m[STEP 4/6] Copy Monitor-App | Failed\e[0m"
    exit;
fi

# Deleting old logs
echo -e "\e[96m[STEP 5/6] Deleting old logs...\e[90m"
if sudo rm /home/appdaemon/.appdaemon/log/*;
then
    echo -e "\e[32m[STEP 5/6] Deleting logs | Done\e[0m"
else
    echo -e "\e[31m[STEP 5/6] Deleting logs | Failed\e[0m"
    exit;
fi

# Restarting AppDaemon
echo -e "\e[96m[STEP 6/6] Restarting AppDaemon...\e[90m"
if sudo systemctl restart appdaemon@appdaemon.service --now;
then
    echo -e "\e[32m[STEP 6/6] Restart AppDaemon | Done\e[0m"
else
    echo -e "\e[31m[STEP 6/6] Restart AppDaemon | Failed\e[0m"
    exit;
fi

echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[32mUpdate finished!\e[0m"
echo -e "\e[0m"
echo -e "\e[32mPlease check logs to see if everything runs as expected.\e[0m"
echo -e "\e[0m"
