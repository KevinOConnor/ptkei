#!/bin/sh

# This script extracts the ptkei files from their CVS tree and creates
# a tar.gz, a zip, and soon a rpm and a deb.

# Check that the version number provided by the user matches the
# following syntax: /^[0-9]+\.[0-9]+\.[0-9]+$/.
checkversion()
{
    error=$(echo -n "$1" | sed -e 's/^[0-9]\+\.[0-9]\+\.[0-9]\+$//' | wc -m)
    if [ $error -eq 0 ]; then
	return 0
    else
	return 1
    fi
}

## MAIN ROUTINE

if [ $# -ne 1 ]; then
    echo "Wrong number of arguments." >&2
    exit 1
fi

checkversion $1
if [ $? -ne 0 ]; then
    echo "Argument provided is not a version string." >&2
    exit 1
fi

version=$1
cvstag=$(echo ptkei.$1 | tr "." "_")
dir=$(echo /tmp/ptkei-$1 | tr "_" ".") 
distdir=$(echo ptkei-$1 | tr "_" ".")

cd /tmp
cvs co -r $cvstag ptkei
if [ $? -ne 0 ]; then
    echo "Error while checking out ptkei version $version" >&2
    exit 1
fi

mv ptkei $dir
if [ $? -ne 0 ]; then 
    echo "Can't create directory $dir" >&2
    exit 1
fi

cd $dir
find . -name CVS -exec rm -r {} \;
[ -f mkdist.sh ] && rm $dir/mkdist.sh
grep -E -e "^version.*$version" empire.py
if [ $? -ne 0 ]; then
    echo "Version number found in file empire.py doesn't match argument $version" >&2
    cd /tmp
#    rm -r $dir
#    exit 1
fi
cd /tmp
tar cvfz $distdir.tar.gz $distdir
zip -r $distdir.zip $distdir
