# ⚙️ Sistema WMS Inteligente para Taller de Reparación
*Arquitectura Orientada a Eventos y Control Dinámico de Inventario*

Desarrollado para el Hackathon de Almacén Inteligente.

---

## 🚀 Descripción del Proyecto
Este sistema soluciona la gestión logística de un taller de reparación de equipo industrial (husillos y motores eléctricos) mediante:
1. **Procesamiento de Eventos:** Lectura y libro mayor inmutable (*append-only*) basado en `events.jsonl`.
2. **Backend Asíncrono (FastAPI):** Expone endpoints REST para control de existencias, kardex, faltantes, sugerencias de compra y operaciones de piso.
3. **Interfaz de Usuario (Streamlit):** Panel gerencial con tableros en tiempo real, control por antigüedad y terminal móvil para operadores.

---

## 📋 Requisitos Previos
* **Python 3.12 o superior** instalado en tu sistema.

---

## 🛠️ Instalación y Ejecución Local (Sin Docker / Sin Redpanda)

No se requiere infraestructura de Kafka ni Docker Desktop. El sistema opera en modo autónomo leyendo directamente el archivo de eventos históricos.

## RECOMENDACION ## 
Cambiar los directorios de dentro del programa a una ruta especificada del tipo: 
C:\hackaton_base\events.jsonl --->> Esto ahorra tiempo y subprocesos en la búsqueda

### 1. Clonar o descargar el repositorio
Abre tu terminal en la carpeta del proyecto.

### 2. Instalar las dependencias
Ejecuta el siguiente comando para instalar FastAPI, Streamlit y Pandas:
```bash
pip install -r requirements.txt
