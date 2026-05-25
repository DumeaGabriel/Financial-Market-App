from pymongo import MongoClient

if __name__ == '__main__':
        conn = MongoClient("mongodb+srv://admin:admin@cluster0.urlpmzv.mongodb.net/")
        db= conn['DataWarehouse']
        collection = db["Asset"]
        for record in collection.find():
                print(record)
