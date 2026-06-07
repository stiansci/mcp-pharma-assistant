# test_server_logic.py (v2 - Testa la logica pura)

import asyncio
import sys
import os

# Aggiungiamo la cartella principale al path di Python
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.append(PROJECT_ROOT)

# Importiamo le funzioni di LOGICA (con underscore)
try:
    from italian_pharma_server import (
        _get_drug_info_by_name, 
        _get_active_ingredients, 
        _check_availability,
        con
    )
    print("Importazione dei componenti di logica dal server riuscita.")
except ImportError as e:
    print(f"Errore di importazione: {e}")
    sys.exit(1)

async def run_tests():
    """Esegue i test sulla logica dei tool."""
    if not con:
        print("ERRORE: Connessione al database non stabilita.")
        return

    print("\n" + "="*80)
    print("INIZIO TEST 1: _get_drug_info_by_name('Tachipirina')")
    print("="*80)
    
    try:
        nome_farmaco = "Tachipirina"
        print(f"Chiamata diretta alla funzione di logica _get_drug_info_by_name('{nome_farmaco}')...")
        
        # Chiamiamo direttamente la funzione asincrona
        risultato = await _get_drug_info_by_name(nome_farmaco)
        
        print("\n--- RISULTATO FINALE RICEVUTO ---")
        if not risultato:
            print("La funzione ha restituito una lista vuota.")
        else:
            print(f"Trovate {len(risultato)} confezioni.")
            for i, item in enumerate(risultato):
                print(f"\n--- Confezione #{i+1} ---")
                print(item.model_dump_json(indent=2))

    except Exception as e:
        print(f"\n!!!!!! ERRORE DURANTE IL TEST 1 !!!!!!")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_tests())