import pymssql
conn = pymssql.connect(server='localhost', port=1433, user='sa', password='rak!@#123', database='SCADA_Historian')
cursor = conn.cursor()
cursor.execute("SELECT 1")
print("Local DB OK")
conn.close()