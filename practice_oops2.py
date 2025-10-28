from operator import truediv


class Computer:
    def __init__(self):
        self.name = "AShok"
        self.age = 45
    def update(self):
        self.age += 2
    def compare(self, other):
        if self.age == other.age:
            return True
        else:
            return False


c1=Computer()
c2=Computer()
c2.name = "Priya"
print(c1.name,c1.age)
#c2.update()
print(c2.name,c2.age)

if c1.compare(c2):
    print("They are the same")
else:
    print("They are different")