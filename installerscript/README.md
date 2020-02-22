# Quick installation & update scripts

### These scripts will perform different options for installation

Choose your selection of installation path below for instructions


### IMPORTANT INFORMATION
> The scripts are tested on Raspberry only (RPi3 & 4) but should work on most Linux distro's and usernames

<br>
<br>

<details><summary><b>Installation & Update Instructions : Standalone - AppDaemon 4.x and Monitor-App</b></summary>
<br>
This script are for a first time install of both AppDaemon 4.x and Monitor-App (tested on Raspberry Pi 4 with Raspbian Buster, but should work fine on Ubuntu and other Linux versions). You will find provided templates of configuration files that will be copied to your device, you will just need to fill in your own information. Description and examples are within the configuration files themselves. To execute the full installscript, run following command from your commandline:
<br>
<br>
`bash -c "$(curl -sL https://raw.githubusercontent.com/Odianosen25/Monitor-App/master/installerscript/install_ad.sh)"`
<br>
If you get an error message about Curl, install curl by do `sudo apt-get install curl -y`
<br>
<br>

<details><summary><i>Update Instructions: Standalone - AppDaemon 4.x and Monitor-App</i></summary>
<br>
To execute the updatescript, run following command from your commandline:
<br>
<br>
`bash -c "$(curl -sL https://raw.githubusercontent.com/Odianosen25/Monitor-App/master/installerscript/update_ad_ma.sh)"`
<br>
<br>

</details></details>
***
<br>
<details><summary><b>Installation Instructions : Standalone - Monitor-App only</b></summary>
This script will install Monitor-App on an existing AppDaemon 4.x installation.
> Please note: The script assumes default path of AppDaemon configuration files and will check this. If not, the script will stop.
<br>
<br>
`bash -c "$(curl -sL https://raw.githubusercontent.com/Odianosen25/Monitor-App/master/installerscript/update_ma_only.sh)"`
<br>
If you get an error message about Curl, install curl by do `sudo apt-get install curl -y`
If you get an error message about Git, install git by do `sudo apt-get install git -y`
</details>
<br>
<br>
This folder contain templates of configuration files to get going, descriptions are inside the tempales.

