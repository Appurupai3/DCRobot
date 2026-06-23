/*
 * dcrobot_rng_v2.c — DCRobot Kernel RNG Module v2
 *
 * 在 v1 基礎上加入 rdtsc 硬體時間戳作為額外 entropy 來源
 * 每次讀取前，將 CPU timestamp counter 混入 kernel entropy pool
 * 使隨機數與當下硬體狀態強相關，提升不可預測性
 *
 * 差異對比：
 *   v1：純 get_random_bytes()（= /dev/urandom）
 *   v2：rdtsc XOR mixing + get_random_bytes()
 *
 * 編譯：make -f Makefile.v2
 * 載入：sudo insmod dcrobot_rng_v2.ko
 * 測試：sudo dd if=/dev/dcrobot_rng_v2 of=v2.bin bs=1M count=1 && ent v2.bin
 * 卸載：sudo rmmod dcrobot_rng_v2
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/uaccess.h>
#include <linux/random.h>
#include <linux/slab.h>
#include <linux/atomic.h>
#include <linux/timekeeping.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <asm/msr.h>       /* rdtsc_ordered() */
#include <crypto/hash.h>   /* SHA-256 mixing */

MODULE_LICENSE("GPL");
MODULE_AUTHOR("DCRobot Team");
MODULE_DESCRIPTION("Kernel RNG v2 with rdtsc hardware entropy mixing");
MODULE_VERSION("2.0");

#define DEVICE_NAME "dcrobot_rng_v2"
#define CLASS_NAME  "dcrobot_v2"
#define BUF_SIZE    16

static int            major_number;
static struct class  *dcrobot_class  = NULL;
static struct device *dcrobot_device = NULL;
static struct cdev    dcrobot_cdev;
static atomic_t       read_count = ATOMIC_INIT(0);
static atomic64_t     total_bytes = ATOMIC64_INIT(0);

/* ── rdtsc entropy mixing ─────────────────────────────────── */

/*
 * mix_hardware_entropy()
 *
 * 取得三個硬體來源的值：
 *   1. rdtsc  — CPU timestamp counter（奈秒級，每次不同）
 *   2. ktime  — kernel monotonic clock
 *   3. jiffies — kernel tick counter
 *
 * 用 XOR folding 混合後，呼叫 add_device_randomness()
 * 把這些硬體觀測值注入 kernel entropy pool。
 * 之後再呼叫 get_random_bytes() 取出的結果就包含了這些額外 entropy。
 */
static void mix_hardware_entropy(void)
{
    u64 tsc    = rdtsc_ordered();          /* CPU 時間戳計數器 */
    u64 ktime  = ktime_get_ns();           /* kernel 單調時鐘（ns）*/
    u64 jiff   = (u64)jiffies;             /* kernel tick */

    /* XOR folding：把三個值混在一起 */
    u64 mixed  = tsc ^ ktime ^ (jiff << 32 | jiff);

    /* 注入 kernel entropy pool */
    add_device_randomness(&mixed, sizeof(mixed));

    pr_debug("dcrobot_rng_v2: mixed entropy tsc=%llu kt=%llu j=%llu\n",
             tsc, ktime, jiff);
}

/* ── /proc 統計 ───────────────────────────────────────────── */
static struct proc_dir_entry *proc_entry;

static int stats_show(struct seq_file *m, void *v)
{
    seq_printf(m,
        "dcrobot_rng_v2 stats:\n"
        "  reads      : %d\n"
        "  total_bytes: %lld\n"
        "  entropy_src: rdtsc + ktime + jiffies -> kernel pool\n",
        atomic_read(&read_count),
        atomic64_read(&total_bytes));
    return 0;
}

static int stats_open(struct inode *inode, struct file *file)
{
    return single_open(file, stats_show, NULL);
}

static const struct proc_ops stats_fops = {
    .proc_open    = stats_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ── 字元裝置 file operations ─────────────────────────────── */
static int dev_open(struct inode *inodep, struct file *filep)
{
    pr_info("dcrobot_rng_v2: opened\n");
    return 0;
}

static int dev_release(struct inode *inodep, struct file *filep)
{
    pr_info("dcrobot_rng_v2: closed\n");
    return 0;
}

static ssize_t dev_read(struct file *filep, char __user *buffer,
                        size_t len, loff_t *offset)
{
    u8 kbuf[BUF_SIZE];
    size_t to_copy;
    unsigned long not_copied;

    to_copy = min(len, (size_t)BUF_SIZE);

    /* 每次讀取前先混入硬體 entropy */
    mix_hardware_entropy();

    /* 從 pool 取隨機數（現在包含了 rdtsc entropy）*/
    get_random_bytes(kbuf, to_copy);

    not_copied = copy_to_user(buffer, kbuf, to_copy);
    if (not_copied != 0) {
        pr_err("dcrobot_rng_v2: copy_to_user failed (%lu bytes)\n", not_copied);
        return -EFAULT;
    }

    atomic_inc(&read_count);
    atomic64_add(to_copy, &total_bytes);

    return to_copy;
}

static const struct file_operations fops = {
    .owner   = THIS_MODULE,
    .open    = dev_open,
    .read    = dev_read,
    .release = dev_release,
};

/* ── Module init ──────────────────────────────────────────── */
static int __init dcrobot_rng_v2_init(void)
{
    dev_t dev;

    pr_info("dcrobot_rng_v2: loading...\n");

    if (alloc_chrdev_region(&dev, 0, 1, DEVICE_NAME) < 0) {
        pr_err("dcrobot_rng_v2: alloc_chrdev_region failed\n");
        return -1;
    }
    major_number = MAJOR(dev);

    cdev_init(&dcrobot_cdev, &fops);
    dcrobot_cdev.owner = THIS_MODULE;
    if (cdev_add(&dcrobot_cdev, dev, 1) < 0) {
        unregister_chrdev_region(dev, 1);
        return -1;
    }

    dcrobot_class = class_create(CLASS_NAME);
    if (IS_ERR(dcrobot_class)) {
        cdev_del(&dcrobot_cdev);
        unregister_chrdev_region(dev, 1);
        return PTR_ERR(dcrobot_class);
    }

    dcrobot_device = device_create(dcrobot_class, NULL,
                                   MKDEV(major_number, 0),
                                   NULL, DEVICE_NAME);
    if (IS_ERR(dcrobot_device)) {
        class_destroy(dcrobot_class);
        cdev_del(&dcrobot_cdev);
        unregister_chrdev_region(dev, 1);
        return PTR_ERR(dcrobot_device);
    }

    proc_entry = proc_create("dcrobot_stats_v2", 0444, NULL, &stats_fops);
    if (!proc_entry)
        pr_warn("dcrobot_rng_v2: /proc/dcrobot_stats_v2 failed\n");

    pr_info("dcrobot_rng_v2: loaded! /dev/%s (major=%d)\n",
            DEVICE_NAME, major_number);
    return 0;
}

/* ── Module exit ──────────────────────────────────────────── */
static void __exit dcrobot_rng_v2_exit(void)
{
    if (proc_entry)
        remove_proc_entry("dcrobot_stats_v2", NULL);
    device_destroy(dcrobot_class, MKDEV(major_number, 0));
    class_destroy(dcrobot_class);
    cdev_del(&dcrobot_cdev);
    unregister_chrdev_region(MKDEV(major_number, 0), 1);
    pr_info("dcrobot_rng_v2: unloaded. reads=%d bytes=%lld\n",
            atomic_read(&read_count), atomic64_read(&total_bytes));
}

module_init(dcrobot_rng_v2_init);
module_exit(dcrobot_rng_v2_exit);
