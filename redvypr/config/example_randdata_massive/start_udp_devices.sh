nprocesses=50
for i in $(seq 1 $nprocesses); do
    hostname=r$i
    echo $hostname
    redvypr -hn $hostname -ng -v -c randdata_udp.yaml>/dev/null &
done
