1. command shell: cd C:\Users\Philipp\SemesterProject\iSDX

2. command shell: vagrant up

3. putty: connect to 127.0.0.1 port 2222

4. login: vagrant, vagrant

5. run mininet: cd iSDX/examples/test-ms/mininet; sudo python r1_simple_sdx.py

6. run logserver: cd iSDX; rm -f SDXLog.log; python logServer.py SDXLog.log

7. run everything else: ./iSDX/launch.sh test-ms 3

8. run sdnsimple: sudo /home/vagrant/iSDX/Bgpdump/bgp_simple.pl -myas 64000 -myip 173.0.255.252 -peerip 172.0.0.31 -peeras 400 -holdtime 9 -keepalive 3 -p /home/vagrant/iSDX/Bgpdump/myroutes -m 10 -n

9. see bgp routes: mininet> a1 telnet localhost bgpd, pwd: sdnip; show ip bgp

10. cleanup: sh ~/iSDX/pctrl/clean.sh