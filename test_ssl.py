import asyncio
import asyncpg
import os

async def main():
    try:
        conn = await asyncpg.connect(
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            database=os.environ["POSTGRES_DB"],
            host=os.environ["POSTGRES_HOST"],
            port=os.environ.get("POSTGRES_PORT", "5432"),
            ssl="require"
        )
        print("Connected with ssl='require'!")
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())
