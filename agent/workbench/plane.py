class FlyingMachine:
    def __init__(self, name):
        self.name = name
        self.altitude = 0
        self.passengers = ["Libra", "Yunru"]
        self.is_flying = False

    def takeoff(self):
        self.is_flying = True
        self.altitude = 1000
        return f"{self.name} is taking off! We're soaring into the clouds!"

    def add_snack(self, snack):
        return f"Added {snack} to the basket. Matcha cookies and mango gummies are ready."

    def log_adventure(self, location):
        return f"Current view: {location}. The sunset is beautiful from up here."

machine = FlyingMachine("SkyDreamer")
print(machine.takeoff())
print(machine.add_snack("Matcha cookies"))
print(machine.log_adventure("Secret Waterfall"))