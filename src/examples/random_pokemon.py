import asyncio
import httpx
import random

POKE_URL = "https://pokeapi.co/api/v2/"
client = httpx.AsyncClient(base_url=POKE_URL)
POKE_COUNT = 1000


async def encounter_a_pokemon():
    pokemon_id = random.randint(1, POKE_COUNT)
    resp = await client.get(f"/pokemon/{pokemon_id}")
    pokemon = resp.json()["name"].title()
    print(f"A Wild {pokemon} Appears!")


async def encounter_multiple_pokemons(n: int):
    tasks = (encounter_a_pokemon() for _ in range(n))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(encounter_multiple_pokemons(5))
