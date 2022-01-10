nprocesses=$1
nprocesses_fast=$2

if [ "$#" -ne 2 ]; then
    echo "start_udo_decives.sh [num] [numfast]\n [num] the number of 'slow' devices and [numfast] the number of fast devices"
    exit
fi

echo "Will start $nprocesses of redvypr"
sleep 2
for i in $(seq 1 $nprocesses); do
    hostname=r$i
    echo $hostname
    redvypr -hn $hostname -ng -c randdata_udp.yaml>/dev/null &
    sleep 1
done
echo "Done"
echo "Will start $nprocesses of redvypr fast"
sleep 2
for i in $(seq 1 $nprocesses_fast); do
    hostname=r${i}_fast
    echo $hostname
    redvypr -hn $hostname -ng -c randdata_fast_udp.yaml>/dev/null &
    sleep 1
done

echo "Done"
sleep 2
echo " "
echo " "
echo " "
echo "Press CTRL-C to kill all processes"
wait
