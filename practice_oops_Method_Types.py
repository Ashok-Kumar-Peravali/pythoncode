# There are 3 types of methods.
#1. Instance Method
#2. Class Method
#3. Static Method

class Student:

    school = "Spirent"
    def __init__(self, m1, m2, m3):
        self.m1 = m1
        self.m2 = m2
        self.m3 = m3

    def avg(self):
        return (self.m1 + self.m2 + self.m3) / 3

    @classmethod
    def get_school(cls):
        return cls.school
    @staticmethod
    def info():
        print("This is static method sample print")


s1= Student(78,89,90)
s2= Student(71,81,93)
print(s1.avg())
print(s2.avg())

print(Student.get_school())
print(Student.info())