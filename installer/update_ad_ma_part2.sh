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
echo -e "\e[96m  Update Part II...\e[90m"
echo -e "\e[0m"


# Install AppDaemon from git
echo -e "\e[96m[STEP 6/10] Updating AppDaemon...\e[90m"
cd /srv/appdaemon

if source bin/activate;
then
    echo -e "\e[32m[STEP 5/10] Moved to AD and ready for update | Done\e[0m"
else
    echo -e "\e[31m[STEP 5/10] Moved to AD and ready for update | Failed\e[0m"
    exit;
fi

if cd /srv/appdaemon/appdaemon;
then
    echo -e "\e[32m[STEP 5/10] Accessing appdaemon folder | Done\e[0m"
else
    echo -e "\e[31m[STEP 5/10] Accessing appdaemon folder | Failed\e[0m"
    exit;
fi

if git pull;
then
    echo -e "\e[32m Downloading latest AppDaemon | Done\e[0m"
else
    echo -e "\e[31m Downloading latest AppDaemon | Failed\e[0m"
    exit;
fi

if pip3 install --upgrade .;
then
    echo -e "\e[32m[STEP 6/10] Updating AppDaemon | Done\e[0m"
else
    echo -e "\e[31m[STEP 6/10] Updating AppDaemon | Failed\e[0m"
    exit;
fi


# Everything are finished and should be running fine
echo -e "\e[0m"
echo -e "\e[0m"
echo -e "\e[32mNow, type \e[96mexit\e[32m to quit AD environment!\e[0m"
echo -e "\e[0m"
echo -e "\e[0m"
exit