#This program is basic practice for OOPS concepts
class Computer:
    def __init__(self, cpu, ram, disk):
        self.cpu = cpu
        self.ram = ram
        self.disk = disk


    def config(self):
        print("Computer config is:",self.cpu, "CPU", self.ram, "RAM", self.disk, "HDD")


com1 = Computer('i5','16GB', '500GB')
com2 = Computer('AMD', '32GB', '1TB')


com1.config()
com2.config()