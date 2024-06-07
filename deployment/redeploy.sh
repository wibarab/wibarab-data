#!/bin/bash
# Run this script to update the VICAV instance to the latest versions. 
# It ...
# * pulls the current code of the web application from github.
# * pulls the current content of the web application from github.
# * optionally creates a backup of the dictionary data on vle-curation
# * copies it to this basex setup and restores it there
#
# Note: Assumes deploy-wibarab-content.bxs
# and this file are in the root directory of your basex setup.
# It assumes wibarab content is in the wibarab-data directory
# and that the VICAV webapp is in the webapp/vicav-app directory
# Needs git.

cd $(dirname $0)

if [ ! -f redeploy.settings ]
then echo Missing settings file. Please copy redeploy.settings.dist to redeploy.settings and fill in the credentials.
fi

. redeploy.settings

if [ "$local_username"x = x -o "$local_password"x = x ]; then echo Missing credentials for local BaseX; exit 1; fi
#------ Settings ---------------------
export USERNAME=$local_username
export PASSWORD=$local_password
#-------------------------------------

#------ Update XQuery code -----------
if [ -d ${BUILD_DIR:-webapp/vicav-app} ]
then
  pushd ${BUILD_DIR:-webapp/vicav-app}
  ret=$?
  if [ $ret != "0" ]; then exit $ret; fi
  if [ "$onlytags"x = 'truex' ]
  then
    git reset --hard
    git pull
    uiversion=$(git describe --tags --abbrev=0)
  else
    git pull
    uiversion=$(git describe --tags --always)
  fi
  echo checking out UI ${uiversion}
  git -c advice.detachedHead=false checkout ${uiversion}
  find ./ -type f -and \( -name '*.js' -or -name '*.html' \) -not \( -path './node_modules/*' -or -path './cypress/*' \) -exec sed -i "s~\@version@~$uiversion~g" {} \;
  popd
fi
#-------------------------------------

#------ Update wibarab data from GitHub repository 
echo updating wibarab-data
if [ ! -d wibarab-data/.git ]; then echo "wibarab-data does not exist or is not a git repository"; fi
pushd wibarab-data
ret=$?
if [ $ret != "0" ]; then exit $ret; fi
if [ "$onlytags"x = 'truex' ]
then
git reset --hard
git pull
dataversion=$(git describe --tags --abbrev=0)
else
git pull
dataversion=$(git describe --tags --always)
fi
echo checking out data ${dataversion}
git -c advice.detachedHead=false checkout ${dataversion}
who=$(git show -s --format='%cN')
when=$(git show -s --format='%as')
message=$(git show -s --format='%B')
revisionDesc=$(sed ':a;N;$!ba;s/\n/\\n/g' <<EOF
<revisionDesc>
  <change n="$dataversion" who="$who" when="$when">
$message
   </change>
</revisionDesc>
EOF
)

#------- copy all images into the "images" directory in the web application directory
echo "copying image files from wibarab-data to vicav-webapp"
for d in $(ls -d vicav_*)
do echo "Directory $d:"
   find "$d" -type f -and \( -name '*.jpg' -or -name '*.JPG' -or -name '*.png' -or -name '*.PNG' -or -name '*.svg' \) -exec cp -v {} ${BUILD_DIR:-../webapp/vicav-app}/images \;
   if [ "$onlytags"x = 'truex' ]
   then
     find "$d" -type f -and -name '*.xml' -exec sed -i "s~\(</teiHeader>\)~$revisionDesc\\n\1~g" {} \;
   fi
done
popd

#------ Update corpus data from GitHub repository 
echo updating corpus-data
if [ ! -d corpus-data/.git ]; then git clone https://github.com/wibarab/corpus-data.git; fi
pushd corpus-data
ret=$?
if [ $ret != "0" ]; then exit $ret; fi
if [ "$onlytags"x = 'truex' ]
then
git reset --hard
git pull
dataversion=$(git describe --tags --abbrev=0)
else
git pull
dataversion=$(git describe --tags --always)
fi
echo checking out data ${dataversion}
git -c advice.detachedHead=false checkout ${dataversion}
who=$(git show -s --format='%cN')
when=$(git show -s --format='%as')
message=$(git show -s --format='%B')
revisionDesc=$(sed ':a;N;$!ba;s/\n/\\n/g' <<EOF
<revisionDesc>
  <change n="$dataversion" who="$who" when="$when">
$message
   </change>
</revisionDesc>
EOF
)
popd

#------ Update feature DB from GitHub repository
echo updating featuredb
if [ ! -d featuredb/.git ]; then git clone https://github.com/wibarab/featuredb.git; fi
pushd corpus-data
ret=$?
if [ $ret != "0" ]; then exit $ret; fi
if [ "$onlytags"x = 'truex' ]
then
git reset --hard
git pull
dataversion=$(git describe --tags --abbrev=0)
else
git pull
dataversion=$(git describe --tags --always)
fi
echo checking out data ${dataversion}
git -c advice.detachedHead=false checkout ${dataversion}
who=$(git show -s --format='%cN')
when=$(git show -s --format='%as')
message=$(git show -s --format='%B')
revisionDesc=$(sed ':a;N;$!ba;s/\n/\\n/g' <<EOF
<revisionDesc>
  <change n="$dataversion" who="$who" when="$when">
$message
   </change>
</revisionDesc>
EOF
)
popd

pushd ${BUILD_DIR:-webapp/vicav-app}
find ./ -type f -and \( -name '*.js' -or -name '*.html' \) -not \( -path './node_modules/*' -or -path './cypress/*' \) -exec sed -i "s~\@data-version@~$dataversion~g" {} \;
popd
sed -i "s~webapp/vicav-app/~${BUILD_DIR:-webapp/vicav-app}/~g" deploy-wibarab-content.bxs
./execute-basex-batch.sh deploy-wibarab-content $1
sed -i "s~../webapp/vicav-app/~${BUILD_DIR:-../webapp/vicav-app}/~g" refresh-project-config.xqtl
./execute-basex-batch.sh refresh-project-config.xqtl $1 >/dev/null
pushd wibarab-data
popd
