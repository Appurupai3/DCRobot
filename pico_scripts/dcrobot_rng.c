/*
 * dcrobot_rng.c — DCRobot Kernel RNG Module
 *
 * 提供 /dev/dcrobot_rng 字元裝置
 * 使用 kernel 內建 get_random_bytes() 產生真隨機數
 * Discord Bot 透過讀取此裝置取得公平隨機數用於博弈遊戲
 *
 * 編譯：make
 * 載入：sudo insmod dcrobot_rng.ko
 * 測試：sudo cat /dev/dcrobot_rng | od -An -tu4 -N4
 * 卸載：sudo rmmod dcrobot_rng
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

MODULE_LICENSE("GPL");
MODULE_AUTHOR("DCRobot Team");
MODULE_DESCRIPTION("Kernel-level RNG for DCRobot Discord Bot");
MODULE_VERSION("1.0");

#define DEVICE_NAME "dcrobot_rng"
#define CLASS_NAME  "dcrobot"
#define BUF_SIZE    16   /* 每次最多讀 16 bytes = 4 個 uint32 */

/* ── 全域變數 ─────────────────────────────────────────── */
static int            major_number;
static struct class  *dcrobot_class  = NULL;
static struct device *dcrobot_device = NULL;
static struct cdev    dcrobot_cdev;

/* 統計：被讀取幾次（可從 /proc/dcrobot_stats 查看）*/
static atomic_t read_count = ATOMIC_INIT(0);

/* ── /proc 統計介面 ───────────────────────────────────── */
#include <linux/proc_fs.h>
#include <linux/seq_file.h>

static struct proc_dir_entry *proc_entry;

static int stats_show(struct seq_file *m, void *v)
{
    seq_printf(m, "dcrobot_rng reads: %d\n", atomic_read(&read_count));
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

/* ── 字元裝置 file operations ─────────────────────────── */
static int dev_open(struct inode *inodep, struct file *filep)
{
    pr_info("dcrobot_rng: opened\n");
    return 0;
}

static int dev_release(struct inode *inodep, struct file *filep)
{
    pr_info("dcrobot_rng: closed\n");
    return 0;
}

static ssize_t dev_read(struct file *filep, char __user *buffer,
                        size_t len, loff_t *offset)
{
    u8 kbuf[BUF_SIZE];
    size_t to_copy;
    unsigned long not_copied;

    /* 限制每次讀取上限 */
    to_copy = min(len, (size_t)BUF_SIZE);

    /* 從 kernel entropy pool 取得真隨機數 */
    get_random_bytes(kbuf, to_copy);

    /* 複製到 user space */
    not_copied = copy_to_user(buffer, kbuf, to_copy);
    if (not_copied != 0) {
        pr_err("dcrobot_rng: failed to copy %lu bytes to user\n", not_copied);
        return -EFAULT;
    }

    atomic_inc(&read_count);
    pr_debug("dcrobot_rng: provided %zu random bytes (total reads: %d)\n",
             to_copy, atomic_read(&read_count));

    return to_copy;
}

static const struct file_operations fops = {
    .owner   = THIS_MODULE,
    .open    = dev_open,
    .read    = dev_read,
    .release = dev_release,
};

/* ── Module init ──────────────────────────────────────── */
static int __init dcrobot_rng_init(void)
{
    dev_t dev;

    pr_info("dcrobot_rng: loading...\n");

    /* 動態分配 major number */
    if (alloc_chrdev_region(&dev, 0, 1, DEVICE_NAME) < 0) {
        pr_err("dcrobot_rng: failed to alloc chrdev region\n");
        return -1;
    }
    major_number = MAJOR(dev);

    /* 初始化 cdev */
    cdev_init(&dcrobot_cdev, &fops);
    dcrobot_cdev.owner = THIS_MODULE;
    if (cdev_add(&dcrobot_cdev, dev, 1) < 0) {
        pr_err("dcrobot_rng: failed to add cdev\n");
        unregister_chrdev_region(dev, 1);
        return -1;
    }

    /* 建立 device class */
    dcrobot_class = class_create(CLASS_NAME);
    if (IS_ERR(dcrobot_class)) {
        pr_err("dcrobot_rng: failed to create class\n");
        cdev_del(&dcrobot_cdev);
        unregister_chrdev_region(dev, 1);
        return PTR_ERR(dcrobot_class);
    }

    /* 建立 /dev/dcrobot_rng */
    dcrobot_device = device_create(dcrobot_class, NULL,
                                   MKDEV(major_number, 0),
                                   NULL, DEVICE_NAME);
    if (IS_ERR(dcrobot_device)) {
        pr_err("dcrobot_rng: failed to create device\n");
        class_destroy(dcrobot_class);
        cdev_del(&dcrobot_cdev);
        unregister_chrdev_region(dev, 1);
        return PTR_ERR(dcrobot_device);
    }

    /* 建立 /proc/dcrobot_stats */
    proc_entry = proc_create("dcrobot_stats", 0444, NULL, &stats_fops);
    if (!proc_entry)
        pr_warn("dcrobot_rng: failed to create /proc/dcrobot_stats\n");

    pr_info("dcrobot_rng: loaded! /dev/%s (major=%d)\n",
            DEVICE_NAME, major_number);
    return 0;
}

/* ── Module exit ──────────────────────────────────────── */
static void __exit dcrobot_rng_exit(void)
{
    if (proc_entry)
        remove_proc_entry("dcrobot_stats", NULL);

    device_destroy(dcrobot_class, MKDEV(major_number, 0));
    class_destroy(dcrobot_class);
    cdev_del(&dcrobot_cdev);
    unregister_chrdev_region(MKDEV(major_number, 0), 1);

    pr_info("dcrobot_rng: unloaded. total reads: %d\n",
            atomic_read(&read_count));
}

module_init(dcrobot_rng_init);
module_exit(dcrobot_rng_exit);
