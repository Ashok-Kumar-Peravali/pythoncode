class car:

    wheels = 4
    def __init__(self):
        self.milage = 10
        self.make = "Tata"


c1 = car()
c2 = car()
print(c1.milage, c1.make, c1.wheels, car.wheels)
c2.milage = 11
car.wheels = 2
print(c2.milage, c2.make, c2.wheels)

# In the above example "wheels" is a 'class variable'. "milage, make" are the instance
# variables. If you change the value of "wheels" all the instances using this variable
# will have the updated value