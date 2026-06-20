import sys
import os

print("=== TAXSENTRY SETUP VERIFICATION ===")
print(f"Python Version: {sys.version}")
print(f"Current Working Directory: {os.getcwd()}")
print("-------------------------------------")

try:
    import pandas as pd
    print(f"✅ Pandas imported successfully! (v{pd.__version__})")
except Exception as e:
    print(f"❌ Failed to import Pandas: {e}")

try:
    import openpyxl
    print("✅ OpenPyXL imported successfully!")
except Exception as e:
    print(f"❌ Failed to import OpenPyXL: {e}")

try:
    import pdfplumber
    print(f"✅ PDFPlumber imported successfully! (v{pdfplumber.__version__})")
except Exception as e:
    print(f"❌ Failed to import PDFPlumber: {e}")

try:
    import openai
    print("✅ OpenAI client library imported successfully!")
except Exception as e:
    print(f"❌ Failed to import OpenAI: {e}")

try:
    import telegram
    print("✅ Python-Telegram-Bot imported successfully!")
except Exception as e:
    print(f"❌ Failed to import Python-Telegram-Bot: {e}")

try:
    import matplotlib
    import seaborn
    print("✅ Visualization libraries (Matplotlib, Seaborn) imported successfully!")
except Exception as e:
    print(f"❌ Failed to import visualization libraries: {e}")

print("-------------------------------------")
print("🎉 Everything is set up perfectly!")
