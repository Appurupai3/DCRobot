obj-m += dcrobot_rng.o
obj-m += dcrobot_rng_v2.o

KDIR := /lib/modules/$(shell uname -r)/build

all:
	make -C $(KDIR) M=$(PWD) modules

clean:
	make -C $(KDIR) M=$(PWD) clean

install_v1:
	sudo insmod dcrobot_rng.ko
	sudo chmod 666 /dev/dcrobot_rng
	@echo "[v1] loaded: /dev/dcrobot_rng"

install_v2:
	sudo insmod dcrobot_rng_v2.ko
	sudo chmod 666 /dev/dcrobot_rng_v2
	@echo "[v2] loaded: /dev/dcrobot_rng_v2"

uninstall:
	-sudo rmmod dcrobot_rng
	-sudo rmmod dcrobot_rng_v2
	@echo "unloaded"

compare:
	@echo "=== 抽樣 1MB 資料 ==="
	sudo dd if=/dev/dcrobot_rng    of=/tmp/v1.bin bs=1M count=1 2>/dev/null
	sudo dd if=/dev/dcrobot_rng_v2 of=/tmp/v2.bin bs=1M count=1 2>/dev/null
	sudo dd if=/dev/urandom        of=/tmp/urandom.bin bs=1M count=1 2>/dev/null
	@echo ""
	@echo "=== v1（純 get_random_bytes）==="
	ent /tmp/v1.bin
	@echo ""
	@echo "=== v2（rdtsc + ktime + jiffies mixing）==="
	ent /tmp/v2.bin
	@echo ""
	@echo "=== /dev/urandom（baseline）==="
	ent /tmp/urandom.bin

stats:
	@echo "=== v1 stats ==="
	cat /proc/dcrobot_stats
	@echo ""
	@echo "=== v2 stats ==="
	cat /proc/dcrobot_stats_v2
