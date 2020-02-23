#!/bin/bash
# Bash script to offer installation and/or updates of Monitor-App and AppDaemon 4.x
# Created for @Odianosen25 and his great app Monitor-App
#
# 
if sudo -q apt-get install dialog && sudo apt-get install curl ;
then
    echo -e "\e[32m\e[0m"
else
    echo -e "\e[31m\e[0m"
 fi


TERMINAL=$(tty)
HEIGHT=20
WIDTH=60
CHOICE_HEIGHT=5
BACKTITLE="TheStigh's installerscript for Monitor-App & AppDaemon 4.x"
TITLE="MENU"
MENU ""
#MENU="This menu gives you choices of what you want to do, either it is installing or updating Monitor-App and/or AppDaemon"

OPTIONS=(1 "Install Standalone AppDaemon & Monitor-App"
         2 "Install Standalone Monitor-App"
         3 "Update Standalone AppDaemon & Monitor-App"
         4 "Update Standalone Monitor-App")

CHOICE=$(dialog --no-lines \
                --clear \
                --backtitle "$BACKTITLE" \
                --title "$TITLE" \
                --menu "$MENU" \
                $HEIGHT $WIDTH $CHOICE_HEIGHT \
                "${OPTIONS[@]}" \
                2>&1 >$TERMINAL)

clear
case $CHOICE in
        1)
           echo "You chose: Install Standalone AppDaemon & Monitor-App"
           bash -c "$(curl -sL https://raw.githubusercontent.com/Odianosen25/Monitor-App/master/installer/install_ad.sh)"
            ;;
        2)
           echo "You chose: Install Standalone Monitor-App"
           bash -c "$(curl -sL https://raw.githubusercontent.com/Odianosen25/Monitor-App/master/installer/install_ma_only.sh)"
            ;;
        3)
           echo "You chose: Update Standalone AppDaemon & Monitor-App"
           bash -c "$(curl -sL https://raw.githubusercontent.com/Odianosen25/Monitor-App/master/installer/update_ad_ma.sh)"
            ;;
        4)
           echo "You chose: Update Standalone Monitor-App"
           bash -c "$(curl -sL https://raw.githubusercontent.com/Odianosen25/Monitor-App/master/installer/update_ma.sh)"
            ;;
esac
