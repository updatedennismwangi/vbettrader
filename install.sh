#!/bin/bash

echo "Setup vbet"

function rootSetup(){
  # Check root privileges
  if (( $EUID != 0 )); then
      echo "Please run as root"
      exit
  fi
}

function userSetup() {
  # Setup User
  echo "Configuring user"
  USER="vbet"
  GROUP="vbet"
  echo "Setting up default user $USER with group $GROUP"
  if ! id "$USER" &>/dev/null; then
      sudo adduser --system --home /home/$USER --disabled-login --group $USER
      echo "Created user $USER"
  fi
}

function filesSetup(){
  # Setup Paths
  echo "Setup filesystem paths"
  HOMEDIR=$( getent passwd "$USER" | cut -d: -f6 )
  RUNDIR="$HOMEDIR/run"
  echo "Configured home directory to $HOMEDIR"
  if [ ! -d $RUNDIR ]
  then
      sudo -u $USER mkdir -p $RUNDIR
      echo "Created run directory in $RUNDIR"
  fi

  APP_DIR=${PWD}
  echo "App directory ${APP_DIR}"
  DIST_FILES=("vbet vweb bin systemd")
  for dist_file in $DIST_FILES
  do
  P="$APP_DIR/$dist_file"
  echo "Copying $P/"
  if [[ -d $P ]]; then
      cp -r "$P/" "$RUNDIR"
  else
      cp "$P" "$RUNDIR"
  fi
  done

  echo "Generating scripts"
  SCRIPT_DIR=$RUNDIR/bin
  SCRIPTS=("vbet", "vweb", "vsite", "vsetup", "vmanage")
  for script_name in $SCRIPTS
  do
    echo "chmod +x $script_name"
    chmod +x $SCRIPT_DIR/$script_name
  done

  echo "Finished unpacking application"

}

function databaseSetup(){
  # Setup Database
  echo "Setup database user"
  DB_NAME="vweb"
  DB_USER="vweb"
  DB_PASSWORD="vbetserver"
  echo "Creating database user $DB_USER"
  sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
  sudo -u postgres psql -c "CREATE DATABASE $DB_NAME WITH OWNER $DB_USER;"
}

function serviceSetup(){
  # Setup Systemd services
  echo "Installing systemd unit file"
  SYSTEMD_UNITS=("vbet vweb")
  SYSTEMD_PATH="/etc/systemd/system/"
  SYSTEMD_RELOAD=false
  for service_file in $SYSTEMD_UNITS
  do
    FILE="$RUNDIR/systemd/$service_file.service"
    if ! [[ -f "$FILE" ]]; then
      echo "Copying systemd config $FILE"
      cp "$FILE" "$SYSTEMD_PATH"
      SYSTEMD_RELOAD=true
    fi
  done

  #Reload system services
  if [ "$SYSTEMD_RELOAD" = true ] ; then
      systemctl daemon-reload
  fi
}


rootSetup
#userSetup
#filesSetup
databaseSetup
#serviceSetup

echo "Installation complete"
