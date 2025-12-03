import time
import subprocess

print("✅ Avvio scheduler.py attivo")

# Loop infinito per eseguire main.py ciclicamente
while True:
    print("🔁 Avvio nuovo ciclo main.py")
    try:
        subprocess.run(["python", "main.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Errore esecuzione main.py: {e}")

    # Aspetta 5 minuti prima del nuovo ciclo
    time.sleep(300)
