class Computer:
    def __init__(self, cpu, ram, disk):
        self.cpu = cpu
        self.ram = ram
        self.disk = disk

    def config(self):
        print("CPU is:", self.cpu, "RAM is:", self.ram, "Disk is:", self.disk)

c1=Computer("i7","16GB","500GB SDD")
c2=Computer("AMD","32GB","500GB SDD")

c1.config()
c2.config()
