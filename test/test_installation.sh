#!/usr/bin/env bash


# Travis: only need to run the installation once, it it not link to a specific python version. They don't need to use CPU for nothing ;)
if [ "X$TRAVIS_PYTHON_VERSION" == "X2.7" ]; then
   echo "Skippping installation tests for travis 2.7 configuration, only need one launch (2.6)"
   exit 0
fi

echo "Launching installations tests for SUITE: $TEST_SUITE"

cd ..

# Only do the test suite we must do
DOCKER_FILES=`ls -1 test/docker-files/docker-file-$TEST_SUITE-*txt`



function print_color {
   export COLOR="$2"
   export TEXT="$1"
   python -c "from opsbro.log import cprint;cprint('$TEXT', color='$COLOR', end='')"
}

export -f print_color

function get_var_name {
   II=$1
   DOCKER_FILE_FULL=`basename $1`
   DOCKER_FILE=`echo "$DOCKER_FILE_FULL" | cut -d'.' -f1| tr "-" "_"`
   echo "$DOCKER_FILE"
}

export SUCCESS_FILE=/tmp/opsbro.test.installation.success
export FAIL_FILE=/tmp/opsbro.test.installation.fail

# Clean results files
> $SUCCESS_FILE
> $FAIL_FILE


function try_installation {
   FULL_PATH=$1
   DO_WHAT=$2

   DOCKER_FILE=`basename $FULL_PATH`
   NOW=$(date +"%H:%M:%S")
   print_color "$DO_WHAT  $DOCKER_FILE : BUILD starting at $NOW \n" "magenta"
   LOG=/tmp/build-and-run.$DOCKER_FILE.log
   rm -fr $LOG
   BUILD=$(docker build --quiet -f $FULL_PATH .  2>&1)
   if [ $? != 0 ]; then
       echo "$BUILD" > $LOG
       print_color "$DO_WHAT  ERROR: $DOCKER_FILE" "red"
       printf " `date` Cannot build. Look at $LOG\n"
       printf "$DOCKER_FILE\n" >> $FAIL_FILE
       cat $LOG
       return
   fi

   if [ "$DO_WHAT" == "BUILD_ONLY" ];then
      print_color "OK: $DOCKER_FILE  build only phase finish" "green"
      return
   fi

   SHA=`echo $BUILD|cut -d':' -f2`

   print_color "$DO_WHAT  $DOCKER_FILE : RUN starting at $NOW \n" "magenta"
   docker run --interactive -a stdout -a stderr --rm=true  "$SHA" 2>>$LOG >>$LOG
   if [ $? != 0 ]; then
       print_color "$DO_WHAT  ERROR: `date` $DOCKER_FILE" "red"
       printf "  Cannot run. Look at $LOG\n"
       printf "$DOCKER_FILE\n" >> $FAIL_FILE
       cat $LOG
       return
   fi
   NOW=$(date +"%H:%M:%S")
   print_color "$DO_WHAT  OK: $DOCKER_FILE" "green"
   printf " at $NOW (log=$LOG)\n"
   printf "$DOCKER_FILE\n" >> $SUCCESS_FILE
}


export -f try_installation

NB_CPUS=`python -c "import multiprocessing;print multiprocessing.cpu_count()"`
echo "Detected number of CPUs: $NB_CPUS"
# Travis: be sure to use the 2 CPU available, and in fact to allow // connections so we keep the test time bellow the limit
if [ "X$TRAVIS" == "Xtrue" ]; then
   NB_CPUS=3
   echo "Travis detected, using $NB_CPUS CPUs"
   # if stats with DUO, allow far more than this
   if [[ $TEST_SUITE == DUO* ]] || [[ $TEST_SUITE == DEMO* ]]; then
      NB_CPUS=6
      echo "Travis detected, and also DUO test based. Allow more CPUs; $NB_CPUS"
   fi
fi


# export TRAVIS var so xargs calls with have it
export TRAVIS=$TRAVIS
echo "================================================= Building all images first:"
echo $DOCKER_FILES | xargs --delimiter=' ' --no-run-if-empty -n 1 -P $NB_CPUS -I {} bash -c 'try_installation "{}" "BUILD_ONLY"'

# Run must be synchronizer if possible, will allow to have less issues in synchronized tests (like DUO or DEMO)
printf "\n\n\n"
echo "================================================= Then Running all images:"
echo $DOCKER_FILES | xargs --delimiter=' ' --no-run-if-empty -n 1 -P $NB_CPUS -I {} bash -c 'try_installation "{}" "RUN"'


printf "Some tests are OK:\n"
cat $SUCCESS_FILE

ALL_ERRORS=$(cat $FAIL_FILE)
if [ "X$ALL_ERRORS" == "X" ]; then
   echo "OK, no errors."
   exit 0
else
   echo "ERRORS: some tests did fail:"
   cat $FAIL_FILE
   exit 1
fi
