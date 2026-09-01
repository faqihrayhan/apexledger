import asyncio
import time

import asyncpg


async def init_db():
    # Retry logic untuk nunggu database benar-benar siap
    for i in range(5):
        try:
            # Konek ke database bawaan (namanya 'postgres')
            conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/postgres')

            try:
                await conn.execute('CREATE DATABASE apexledger')
                print("✅ Database 'apexledger' berhasil dibuat!")
            except asyncpg.exceptions.DuplicateDatabaseError:
                print("✅ Database 'apexledger' sudah ada, aman!")

            await conn.close()
            return
        except Exception:
            print(f"Menunggu database siap... ({i+1}/5)")
            time.sleep(2)
    print("Gagal konek ke database lokal.")

asyncio.run(init_db())
