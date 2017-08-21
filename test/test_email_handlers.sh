#!/usr/bin/env bash


sleep 5

echo "Starting to test handlers"

NB_EMAILS_DEFERED=$(find /var/spool/postfix/defer* -type f | wc -l)
NB_EMAILS_ACTIVE=$(find /var/spool/postfix/active -type f | wc -l)


if [ $NB_EMAILS_DEFERED -eq 0 ] && [ $NB_EMAILS_ACTIVE -eq 0 ]; then
    echo "There is no email generated by handlers, error active=$NB_EMAILS_ACTIVE  defered*=$NB_EMAILS_DEFERED "
    exit 2
fi


echo "Email handler OK"