import csv
from collections import defaultdict

car_brands = set()
car_models = defaultdict(list)
trim_id = []

with open('carapi-opendatafeed-sample.csv', 'r') as file:
    reader = csv.DictReader(file)
    i = 0
    for row in reader:
        tbrands = row['Make Name']
        tmodels = f"{row['Model Name']} {row['Trim Year']}"
        trim_id.append(row['Trim Id'])
        car_brands.add(tbrands)
        car_models[tbrands].append(tmodels)

        i += 1
        if i == 5:
            break
print(trim_id)
print(car_models)