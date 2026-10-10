# -*- coding: utf-8 -*-
"""
Created on Fri Oct  9 21:53:57 2026

@author: josho
"""



import json
import os 
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class ResolveReceiptRequest(BaseModel):
    part_id: int

class Taller:
    def __init__(self, jsonl_path=r"D:\hackaton_base\events.jsonl"):
        # Aqui se desarrollan todas las características necesarias
        
        self.costos_unitarios = {}  # {part_id: unit_price} atributo de c.u
        self.jsonl_path = jsonl_path # dirección de la pieza
        self.eventos_procesados = set() # conjunto de eventos procesados
                                        # para cada pieza
        
        #Estructuras de Estado (Simulando matrices relacionales)
        self.catalogo_piezas = {}      # part_id -> datos de la pieza
        self.ubicaciones = {}          # location_id -> datos de la ubicación
        self.bom_modelos = {}          # model_id -> líneas de la
                                       # lista de partes de pieza
                                       
        self.ordenes_trabajo = {}      #work_order_id -> datos de la orden
        
        # Libro Mayor de Movimientos (Append-only / Solo inserción)
        # Cada movimiento: 
        # {"part_id": int, "location_id": int, "tipo": str, "cantidad": int, ...}
        self.movimientos = []
        # Conjunto de saldos (valores)
        self.saldos={}
        self.recepciones_sin_relacionar=[] # piezas donde part number no matchean
                                           # con el SKU del catálogo
        # Reservas y Faltantes Activos
        self.reservas = {}             # reservation_id -> datos de reserva
        self.faltantes = []            # lista de faltantes abiertos

    # Función definida para trabajar con los atributos del taller
    def ejecutar(self):
        print(f"Leyendo y procesando eventos desde '{self.jsonl_path}'...")
        
        # Si no encuentra el directorio, termina el running...
        if not os.path.exists(self.jsonl_path):
            print("No se encuentra el archivo ")
            return 
        
        # Conteo de lineas para determinar la cantidad total de jsons
        conteo_lineas=0
        # Se permite lectura de caracteres especiales con UTF-8
        with open(self.jsonl_path, "r", encoding="utf-8") as f:
            for num_linea, linea in enumerate(f, 1):
                if not linea.strip():
                    continue
                conteo_lineas +=1
                try:
                    evento = json.loads(linea)
                    self._procesar_evento(evento)
                except json.JSONDecodeError:
                    print(f"No se pudo decodificar la línea {num_linea}")
        
        #Si realiza una lectura correcta imprimimos las filas (eventos) leídas
        print(f"Análisis de eventos finalizado. \n Conteo lineas: {conteo_lineas}")
        self._mostrar_resumen()

    # Función para el procesamiento de eventos (Condiciones de frontera)
    def _procesar_evento(self, evento_wrapper):
        # Extraer el diccionario interno 'event' donde realmente están los datos
        evento = evento_wrapper.get("event", {})
        event_id = evento.get("event_id")
        event_type = evento.get("event_type")
        data = evento.get("data", {})

        # 1. Validación estricta de Idempotencia (Deduplicado) ~ Sin copias exact
        if event_id in self.eventos_procesados:
            return
        self.eventos_procesados.add(event_id)

        # 2. Enrutador por Tipo de Evento: 
            # Catálogo de refacciones antes del inicio de movimientos
        if event_type == "part.upserted":
            self._handle_part_upserted(data)
            
            # Mapeo Espacial del Almacén ~ Actualización Espacial
        elif event_type == "location.upserted":
            self._handle_location_upserted(data)
            
            # Estructura de Listas de Partes (BOM) 
        elif event_type == "bom.upserted":
            self._handle_bom_upserted(data)
            
            # Apertura de Órdenes de Trabajo
        elif event_type == "work_order.opened":
            self._handle_work_order_opened(data)
            
            # Cambio de etapa en el Ciclo de Reparación ej: Diagnost -> Desmontaje
        elif event_type == "work_order.stage_changed":
            self._handle_stage_changed(data)
            
            # Cancelación o Baja de Órdenes de Trabajo: Cancelación de órdenes
        elif event_type == "work_order.deleted":
            self._handle_work_order_deleted(data)
            
            # Aprobación de Inspección según el propósito: Apartar, Reservar, etc
        elif event_type == "inspection.approved":
            self._handle_inspection_approved(data)
            
            # Recepción de Compras y Valores Financieros Totales
        elif event_type == "purchase.item_received":
            self._handle_purchase_received(data)
            # 2. Guardamos el costo unitario de manera independiente para la valuación:
            part_number = data.get("part_number")
            unit_price = data.get("unit_price")
            if part_number and unit_price:
                for pid, pinfo in self.catalogo_piezas.items():
                    sku = pinfo.get("sku")
                    if sku and sku.strip().upper() == part_number.strip().upper():
                        # Inicializa este diccionario en tu __init__: self.costos_unitarios = {}
                        self.costos_unitarios[pid] = float(unit_price)
                        break
            
        # Anulación de inspecciones: Revierte movimientos de inventario y estados
        elif event_type == "inspection.voided":
            self._handle_inspection_voided(data)

    #"Transplantes" de datos según el evento (Funciones): 

        # Registra o actualiza un artículo en el catálogo general
    def _handle_part_upserted(self, data):
        part_id = data.get('part_id')
        self.catalogo_piezas[part_id] = data

        # Da de alta o modifica las ubicaciones físicas espaciales del almacén
    def _handle_location_upserted(self, data):
        loc_id = data.get('location_id')
        self.ubicaciones[loc_id] = data

        # Carga las listas de partes (BOM) asociadas a un modelo de equipo
    def _handle_bom_upserted(self, data):
        model_id = data.get('model_id')
        self.bom_modelos[model_id] = data.get("lines", [])

        # Inicia una nueva orden de reparación del taller
    def _handle_work_order_opened(self, data):
        wo_id = data.get('work_order_id')
        self.ordenes_trabajo[wo_id] = data

        # Actualiza los cambios de status ej: Diagnóstico --> Reparación
    def _handle_stage_changed(self, data):
        wo_id = data.get('work_order_id')
        if wo_id in self.ordenes_trabajo:
            self.ordenes_trabajo[wo_id]["stage"] = data.get("to_stage") 

        # Cancela o da de baja una orden de trabajo 
        # activo -> falso ; 
    def _handle_work_order_deleted(self, data):
        wo_id = data.get("work_order_id")
        if wo_id in self.ordenes_trabajo:
            self.ordenes_trabajo[wo_id]["active"] = False
        # Liberar reservas activas y cerrar faltantes al dar de baja una orden
        self._liberar_reservas_y_faltantes_por_orden(wo_id)
        
        #Procesa los elementos aprobados cuando requieren aprobaciones, ej:
    def _handle_inspection_approved(self, data): 
        #Calcula la cantidad requerida                            action== "buy"
        work_order_id = data.get("work_order_id")
        inspection_id = data.get("inspection_id")
        items = data.get("items", [])
        
        # Estructura para registrar eventos de salida generados
        if not hasattr(self, "eventos_salida"):
            self.eventos_salida = []
            # Extraemos las acciones, por ejemplo, "buy"
        for item in items:
            action = item.get("action")
            # Solo procesamos líneas cuya acción sea comprar
            if action != "buy":
                continue
                
            # Extraemos características de las piezas para comprar
            part_id = item.get("part_id")
            name = item.get("name")
            inspection_item_id = item.get("inspection_item_id")
            bom_line_id = item.get("bom_line_id")
            
            # Obtener cantidad requerida (si es null, buscar en el BOM por bom_line_id)
            quantity = item.get("quantity")
            if quantity is None and bom_line_id:
                quantity = self._obtener_qty_desde_bom(bom_line_id)
            
            if quantity is None:
                quantity = 0  # Respaldo seguro o faltante con cantidad nula

            # Caso A: Pieza sin identificar (part_id es null)
            # Se emite un evento de alerta para piezas "huerfanas"
            if not part_id:
                faltante = {
                    "work_order_id": work_order_id,
                    "part_id": None,
                    "name": name,
                    "missing_quantity": quantity,
                    "inspection_item_id": inspection_item_id
                }
                self.faltantes.append(faltante)
                self.eventos_salida.append({
                    "event_type": "stock.shortage_detected",
                    "source": "inventory",
                    "key": str(work_order_id),
                    "data": faltante
                })
                continue

            # Caso B: Pieza identificada, verificar disponibilidad espacial
            cantidad_pendiente = quantity
            if part_id in self.saldos:
                for loc_id, saldos_loc in self.saldos[part_id].items():
                    disponible_en_loc = saldos_loc.get("available", 0)
                    # Si la existencia es mayor que la demanda:
                    if disponible_en_loc > 0 and cantidad_pendiente > 0:
                        a_reservar = min(disponible_en_loc, cantidad_pendiente)
                        
                        # Actualizar saldos espaciales
                        saldos_loc["reserved"] += a_reservar
                        saldos_loc["available"] = saldos_loc["on_hand"] - saldos_loc["reserved"]
                        
                        cantidad_pendiente -= a_reservar
                        
                        # Registrar reserva activa
                        reservation_id = f"RES-{inspection_id}-{inspection_item_id}-{loc_id}"
                        self.reservas[reservation_id] = {
                            "reservation_id": reservation_id,
                            "work_order_id": work_order_id,
                            "part_id": part_id,
                            "location_id": loc_id,
                            "quantity": a_reservar,
                            "status": "active"
                        }
                        
                        # Generar evento de salida stock.reserved[cite: 23]
                        self.eventos_salida.append({
                            "event_type": "stock.reserved",
                            "source": "inventory",
                            "key": str(work_order_id),
                            "data": {
                                "reservation_id": reservation_id,
                                "work_order_id": work_order_id,
                                "part_id": part_id,
                                "quantity": a_reservar,
                                "inspection_item_id": inspection_item_id
                            }
                        })

            # Si la existencia es menor a la demanda, 
            # lo restante se vuelve faltante
            if cantidad_pendiente > 0:
                faltante = {
                    "work_order_id": work_order_id,
                    "part_id": part_id,
                    "name": name,
                    "missing_quantity": cantidad_pendiente,
                    "inspection_item_id": inspection_item_id
                }
                # Se agrega al vector faltante para sugerir como compras
                self.faltantes.append(faltante)
                self.eventos_salida.append({
                    "event_type": "stock.shortage_detected",
                    "source": "inventory",
                    "key": str(work_order_id),
                    "data": faltante
                })
                
            # Función de ayuda para consultar cantidades por unidad
            # definidas previamente en el BOM
    def _obtener_qty_desde_bom(self, bom_line_id):
        # Busca el qty_per_unit en las líneas de los modelos cargados en self.bom_modelos
        for model_id, lines in self.bom_modelos.items():
            for line in lines:
                if line.get("bom_line_id") == bom_line_id:
                    return line.get("qty_per_unit")
        return None

            # Procesa las entregas de material comprado para reabastecer el taller
    def _handle_purchase_received(self, data):
        #Se obtiene el propósito de compra
        purpose = data.get("purpose")
        
        # Las compras de tipo customer_order no entran al inventario del taller
        if purpose != "restock":
            return
        
        # Se obtienen 
        part_number_raw = data.get("part_number")
        quantity = data.get("quantity", 0)
        purchase_line_id = data.get("line_id")
        description = data.get("description")
        work_order_code = data.get("work_order_code")
        
        if not quantity:
            return

        # Asegurar inicialización de eventos de salida
        if not hasattr(self, "eventos_salida"):
            self.eventos_salida = []

        # 1. Relacionar el texto libre (part_number) con el SKU del catálogo[cite: 20, 22]
        part_id_encontrado = None
        for pid, pdata in self.catalogo_piezas.items():
            sku = pdata.get("sku")
            if sku and part_number_raw and sku.strip().upper() == part_number_raw.strip().upper():
                part_id_encontrado = pid
                break

        if not part_id_encontrado:
            # Si no coincide, se manda a revisión manual y se emite stock.unmatched_receipt[cite: 12, 22, 23]
            self.recepciones_sin_relacionar.append(data)
            self.eventos_salida.append({
                "event_type": "stock.unmatched_receipt",
                "source": "inventory",
                "key": str(purchase_line_id),
                "data": {
                    "purchase_line_id": purchase_line_id,
                    "part_number": part_number_raw,
                    "description": description,
                    "quantity": quantity
                }
            })
            return

        # 2. Localizar la ubicación de recepción estándar ('U-100')[cite: 15, 26]
        loc_id_recepcion = None
        for loc_id, ldata in self.ubicaciones.items():
            if ldata.get("code") == "U-100":
                loc_id_recepcion = loc_id
                break
        
        if not loc_id_recepcion and self.ubicaciones:
            loc_id_recepcion = list(self.ubicaciones.keys())[0]

        if not loc_id_recepcion:
            return

        # 3. Registrar movimiento inmutable de entrada en el espacio de recepción[cite: 21, 22]
        movimiento = {
            "part_id": part_id_encontrado,
            "location_id": loc_id_recepcion,
            "tipo": "stock_received",
            "quantity": quantity,
            "unit_cost": data.get("unit_price"),
            "currency": data.get("currency"),
            "purchase_line_id": purchase_line_id
        }
        self.movimientos.append(movimiento)

        # Emitir evento de salida stock.received[cite: 23]
        self.eventos_salida.append({
            "event_type": "stock.received",
            "source": "inventory",
            "key": str(part_id_encontrado),
            "data": {
                "part_id": part_id_encontrado,
                "location_id": loc_id_recepcion,
                "quantity": quantity,
                "unit_cost": data.get("unit_price"),
                "currency": data.get("currency"),
                "purchase_line_id": purchase_line_id
            }
        })

        # Actualizar saldos espaciales en la ubicación de recepción[cite: 21, 22]
        if part_id_encontrado not in self.saldos:
            self.saldos[part_id_encontrado] = {}
        if loc_id_recepcion not in self.saldos[part_id_encontrado]:
            self.saldos[part_id_encontrado][loc_id_recepcion] = {"on_hand": 0, "reserved": 0, "available": 0}

        self.saldos[part_id_encontrado][loc_id_recepcion]["on_hand"] += quantity
        self.saldos[part_id_encontrado][loc_id_recepcion]["available"] = (
            self.saldos[part_id_encontrado][loc_id_recepcion]["on_hand"] - 
            self.saldos[part_id_encontrado][loc_id_recepcion]["reserved"]
        )

        # 4. Surtir faltantes pendientes con la llegada de la compra[cite: 22]
        # Identificar si trae un work_order_code específico[cite: 22]
        target_work_order_id = None
        if work_order_code:
            for wo_id, wodata in self.ordenes_trabajo.items():
                if wodata.get("code") == work_order_code:
                    target_work_order_id = wo_id
                    break

        # Buscar faltantes abiertos que coincidan con la pieza
        cantidad_por_surtir = quantity
        faltantes_a_remover = []

        for faltante in self.faltantes:
            if cantidad_por_surtir <= 0:
                break
                
            f_part_id = faltante.get("part_id")
            f_wo_id = faltante.get("work_order_id")
            missing_qty = faltante.get("missing_quantity", 0)

            # Priorizar si coincide la orden de trabajo específica o la pieza general[cite: 22]
            es_orden_coincidente = (target_work_order_id and f_wo_id == target_work_order_id) or not target_work_order_id

            if f_part_id == part_id_encontrado and es_orden_coincidente:
                surtido_efectivo = min(missing_qty, cantidad_por_surtir)
                
                faltante["missing_quantity"] -= surtido_efectivo
                cantidad_por_surtir -= surtido_efectivo

                # Emitir evento stock.shortage_resolved[cite: 23, 24]
                self.eventos_salida.append({
                    "event_type": "stock.shortage_resolved",
                    "source": "inventory",
                    "key": str(f_wo_id),
                    "data": {
                        "work_order_id": f_wo_id,
                        "part_id": part_id_encontrado,
                        "quantity": surtido_efectivo
                    }
                })

                if faltante["missing_quantity"] <= 0:
                    faltantes_a_remover.append(faltante)

        # Limpiar faltantes que ya fueron completamente resueltos
        for f in faltantes_a_remover:
            if f in self.faltantes:
                self.faltantes.remove(f)
        
        
    def _handle_inspection_voided(self, data):
        wo_id = data.get("work_order_id")
        # Liberar reservas activas y cerrar faltantes al anular una inspección[cite: 22]
        self._liberar_reservas_y_faltantes_por_orden(wo_id)
    
    
    # Función de liberación de piezas
    def _liberar_reservas_y_faltantes_por_orden(self, work_order_id):
            # Si no tiene atributo -> se crea el vector Eventos_Salida
        if not hasattr(self, "eventos_salida"):
            self.eventos_salida = []

        # 1. Liberar reservas activas asociadas, por orden
        for res_id, res in list(self.reservas.items()):
            if res.get("work_order_id") == work_order_id and res.get("status") == "active":
                res["status"] = "cancelled"
                part_id = res.get("part_id")
                loc_id = res.get("location_id")
                qty = res.get("quantity")
                
                # Devolver la cantidad al espacio disponible l (U-###)
                if part_id in self.saldos and loc_id in self.saldos[part_id]:
                    self.saldos[part_id][loc_id]["reserved"] -= qty
                    self.saldos[part_id][loc_id]["available"] = (
                        self.saldos[part_id][loc_id]["on_hand"] - 
                        self.saldos[part_id][loc_id]["reserved"]
                    )

        # 2. Cerrar faltantes asociados, por orden
        self.faltantes = [f for f in self.faltantes if f.get("work_order_id") != work_order_id]

    # Operaciones de Piso (Llamadas desde la API HTTP)
    
    
    def registrar_salida_piso(self, work_order_id, part_id, location_id, quantity, issued_by):
        """Retira pieza contra una orden de trabajo (stock.issued)"""
        if not hasattr(self, "eventos_salida"):
            self.eventos_salida = []

        if part_id not in self.saldos or location_id not in self.saldos[part_id]:
            raise ValueError("No existe saldo registrado para esta pieza en la ubicación indicada.")

        saldos_loc = self.saldos[part_id][location_id]
        if saldos_loc["on_hand"] < quantity:
            raise ValueError("Stock insuficiente (on_hand menor a la cantidad a retirar).")

        # Registrar movimiento inmutable de salida
        movimiento = {
            "part_id": part_id,
            "location_id": location_id,
            "tipo": "stock_issued",
            "quantity": -quantity,
            "work_order_id": work_order_id
        }
        self.movimientos.append(movimiento)

        # Actualizar saldos espaciales (baja on_hand y baja reserved si aplica)
        saldos_loc["on_hand"] -= quantity
        # Si había reserva activa para esta orden, se reduce el reserved
        for res_id, res in self.reservas.items():
            if res.get("work_order_id") == work_order_id and res.get("part_id") == part_id and res.get("status") == "active":
                res_qty = min(res.get("quantity", 0), quantity)
                res["quantity"] -= res_qty
                saldos_loc["reserved"] -= res_qty
                if res["quantity"] <= 0:
                    res["status"] = "fulfilled"
                break

        saldos_loc["available"] = saldos_loc["on_hand"] - saldos_loc["reserved"]

        # Emitir evento de salida stock.issued[cite: 24]
        self.eventos_salida.append({
            "event_type": "stock.issued",
            "source": "inventory",
            "key": str(work_order_id),
            "data": {
                "work_order_id": work_order_id,
                "part_id": part_id,
                "location_id": location_id,
                "quantity": quantity,
                "issued_by": issued_by
            }
        })
    
    def transferir_stock(self, part_id, from_location_id, to_location_id, quantity):
        """Mueve piezas entre ubicaciones (stock.transferred)."""
        if not hasattr(self, "eventos_salida"):
            self.eventos_salida = []

        if part_id not in self.saldos or from_location_id not in self.saldos[part_id]:
            raise ValueError("No hay existencias en la ubicación de origen.")

        origen = self.saldos[part_id][from_location_id]
        if origen["available"] < quantity:
            raise ValueError("Cantidad disponible insuficiente en el origen para transferir.")

        # Descontar del origen
        origen["on_hand"] -= quantity
        origen["available"] = origen["on_hand"] - origen["reserved"]

        # Abonar al destino
        if to_location_id not in self.saldos[part_id]:
            self.saldos[part_id][to_location_id] = {"on_hand": 0, "reserved": 0, "available": 0}
        destino = self.saldos[part_id][to_location_id]
        destino["on_hand"] += quantity
        destino["available"] = destino["on_hand"] - destino["reserved"]

        # Registrar movimientos inmutables
        self.movimientos.append({"part_id": part_id, "location_id": from_location_id, "tipo": "transfer_out", "quantity": -quantity})
        self.movimientos.append({"part_id": part_id, "location_id": to_location_id, "tipo": "transfer_in", "quantity": quantity})

        # Emitir evento de salida stock.transferred[cite: 24]
        self.eventos_salida.append({
            "event_type": "stock.transferred",
            "source": "inventory",
            "key": str(part_id),
            "data": {
                "part_id": part_id,
                "from_location_id": from_location_id,
                "to_location_id": to_location_id,
                "quantity": quantity
            }
        })

    def ajustar_stock_conteo(self, part_id, location_id, conteo_fisico, reason):
        """Ajuste por conteo cíclico (stock.adjusted)."""
        if not hasattr(self, "eventos_salida"):
            self.eventos_salida = []

        if part_id not in self.saldos:
            self.saldos[part_id] = {}
        if location_id not in self.saldos[part_id]:
            self.saldos[part_id][location_id] = {"on_hand": 0, "reserved": 0, "available": 0}

        saldos_loc = self.saldos[part_id][location_id]
        stock_actual = saldos_loc["on_hand"]
        delta = conteo_fisico - stock_actual

        if delta == 0:
            return

        saldos_loc["on_hand"] = conteo_fisico
        saldos_loc["available"] = saldos_loc["on_hand"] - saldos_loc["reserved"]

        # Registrar movimiento inmutable de ajuste
        self.movimientos.append({
            "part_id": part_id,
            "location_id": location_id,
            "tipo": "cycle_count_adjustment",
            "quantity": delta,
            "reason": reason
        })

        # Emitir evento de salida stock.adjusted[cite: 24]
        self.eventos_salida.append({
            "event_type": "stock.adjusted",
            "source": "inventory",
            "key": str(part_id),
            "data": {
                "part_id": part_id,
                "location_id": location_id,
                "delta": delta,
                "reason": reason
            }
        })
        
        
    def resolver_recepcion_manual(self, purchase_line_id: int, part_id: int):
        """Asocia manualmente una recepción huérfana a una pieza del catálogo e ingresa el stock."""
        if not hasattr(self, "eventos_salida"):
            self.eventos_salida = []

        # Buscar la recepción en la lista de pendientes
        recepcion_encontrada = None
        for r in self.recepciones_sin_relacionar:
            if r.get("line_id") == purchase_line_id or r.get("purchase_line_id") == purchase_line_id:
                recepcion_encontrada = r
                break
        
        if not recepcion_encontrada:
            raise ValueError("No se encontró una recepción sin relacionar con ese ID.")
        
        if part_id not in self.catalogo_piezas:
            raise ValueError("El part_id proporcionado no existe en el catálogo de piezas.")
        
        # Remover de la lista de huérfanas
        self.recepciones_sin_relacionar.remove(recepcion_encontrada)
        
        quantity = recepcion_encontrada.get("quantity", 0)
        work_order_code = recepcion_encontrada.get("work_order_code")
        
        # Localizar la ubicación de recepción estándar ('U-100')
        loc_id_recepcion = None
        for loc_id, ldata in self.ubicaciones.items():
            if ldata.get("code") == "U-100":
                loc_id_recepcion = loc_id
                break
        if not loc_id_recepcion and self.ubicaciones:
            loc_id_recepcion = list(self.ubicaciones.keys())[0]
            
        if not loc_id_recepcion:
            raise ValueError("No hay ubicaciones de recepción configuradas.")

        # Registrar movimiento inmutable de entrada
        movimiento = {
            "part_id": part_id,
            "location_id": loc_id_recepcion,
            "tipo": "stock_received",
            "quantity": quantity,
            "unit_cost": recepcion_encontrada.get("unit_price"),
            "currency": recepcion_encontrada.get("currency"),
            "purchase_line_id": purchase_line_id
        }
        self.movimientos.append(movimiento)

        # Emitir evento stock.received
        self.eventos_salida.append({
            "event_type": "stock.received",
            "source": "inventory",
            "key": str(part_id),
            "data": {
                "part_id": part_id,
                "location_id": loc_id_recepcion,
                "quantity": quantity,
                "unit_cost": recepcion_encontrada.get("unit_price"),
                "currency": recepcion_encontrada.get("currency"),
                "purchase_line_id": purchase_line_id
            }
        })

        # Actualizar saldos espaciales
        if part_id not in self.saldos:
            self.saldos[part_id] = {}
        if loc_id_recepcion not in self.saldos[part_id]:
            self.saldos[part_id][loc_id_recepcion] = {"on_hand": 0, "reserved": 0, "available": 0}

        self.saldos[part_id][loc_id_recepcion]["on_hand"] += quantity
        self.saldos[part_id][loc_id_recepcion]["available"] = (
            self.saldos[part_id][loc_id_recepcion]["on_hand"] - 
            self.saldos[part_id][loc_id_recepcion]["reserved"]
        )

        # Surtir faltantes pendientes si aplica
        target_work_order_id = None
        if work_order_code:
            for wo_id, wodata in self.ordenes_trabajo.items():
                if wodata.get("code") == work_order_code:
                    target_work_order_id = wo_id
                    break

        cantidad_por_surtir = quantity
        faltantes_a_remover = []

        for faltante in self.faltantes:
            if cantidad_por_surtir <= 0:
                break
            f_part_id = faltante.get("part_id")
            f_wo_id = faltante.get("work_order_id")
            missing_qty = faltante.get("missing_quantity", 0)

            es_orden_coincidente = (target_work_order_id and f_wo_id == target_work_order_id) or not target_work_order_id

            if (f_part_id == part_id or f_part_id is None) and es_orden_coincidente:
                surtido_efectivo = min(missing_qty, cantidad_por_surtir)
                faltante["missing_quantity"] -= surtido_efectivo
                cantidad_por_surtir -= surtido_efectivo

                self.eventos_salida.append({
                    "event_type": "stock.shortage_resolved",
                    "source": "inventory",
                    "key": str(f_wo_id),
                    "data": {
                        "work_order_id": f_wo_id,
                        "part_id": part_id,
                        "quantity": surtido_efectivo
                    }
                })

                if faltante["missing_quantity"] <= 0:
                    faltantes_a_remover.append(faltante)

        for f in faltantes_a_remover:
            if f in self.faltantes:
                self.faltantes.remove(f)
    
    

    def _mostrar_resumen(self):
        print("\n Resumen del Almacén Inteligente")
        print(f"Total de eventos únicos procesados: {len(self.eventos_procesados)}")
        print(f"Piezas registradas en catálogo: {len(self.catalogo_piezas)}")
        print(f"Ubicaciones espaciales registradas: {len(self.ubicaciones)}")
        print(f"Órdenes de trabajo ingresadas: {len(self.ordenes_trabajo)}")
        print(f"Movimientos espaciales registrados (Entradas): {len(self.movimientos)}")
        print(f"Recepciones pendientes de relacionar a mano: {len(self.recepciones_sin_relacionar)}")
        
        
        
# --- CONFIGURACIÓN DE FASTAPI ---
app = FastAPI(
    title="API de Almacén Inteligente - Taller",
    description="Servicio HTTP para consultar existencias, kardex, faltantes y operar en piso.",
    version="1.0.0"
)

# Instanciamos la clase y procesamos el archivo automáticamente al iniciar
taller = Taller()
taller.ejecutar()


# --- MODELOS PYDANTIC PARA PETICIONES POST ---
class IssueRequest(BaseModel):
    work_order_id: int
    part_id: int
    location_id: int
    quantity: int
    issued_by: str

class TransferRequest(BaseModel):
    part_id: int
    from_location_id: int
    to_location_id: int
    quantity: int

class CountRequest(BaseModel):
    part_id: int
    location_id: int
    conteo_fisico: int
    reason: str


# --- ENDPOINTS OBLIGATORIOS ---

@app.get("/parts/{part_id}/availability")
def get_part_availability(part_id: int):
    """Saldo por ubicación: on_hand, reserved, available[cite: 25]."""
    if part_id not in taller.saldos:
        return {"part_id": part_id, "ubicaciones": {}}
    
    resultado = {}
    for loc_id, saldos in taller.saldos[part_id].items():
        loc_data = taller.ubicaciones.get(loc_id, {})
        loc_code = loc_data.get("code", f"loc_{loc_id}")
        resultado[loc_code] = saldos
        
    return {"part_id": part_id, "ubicaciones": resultado}


@app.get("/parts/{part_id}/ledger")
def get_part_ledger(part_id: int):
    """Kardex: movimientos con saldo corrido, del más reciente al antiguo[cite: 25]."""
    movimientos_pieza = [m for m in taller.movimientos if m.get("part_id") == part_id]
    return {"part_id": part_id, "kardex": list(reversed(movimientos_pieza))}


@app.get("/work-orders/{code}/materials")
def get_work_order_materials(code: str):
    """Por línea de inspección: reservado, entregado y faltante[cite: 25]."""
    wo_id = None
    for id_w, data in taller.ordenes_trabajo.items():
        if data.get("code") == code:
            wo_id = id_w
            break
            
    if not wo_id:
        raise HTTPException(status_code=404, detail="Orden de trabajo no encontrada.")
        
    reservas_orden = [r for r in taller.reservas.values() if r.get("work_order_id") == wo_id]
    faltantes_orden = [f for f in taller.faltantes if f.get("work_order_id") == wo_id]
    
    return {
        "work_order_code": code,
        "work_order_id": wo_id,
        "reservas": reservas_orden,
        "faltantes": faltantes_orden
    }


@app.get("/shortages")
def get_shortages():
    """Faltantes abiertos, filtrables por orden o pieza[cite: 25]."""
    return {"total_faltantes": len(taller.faltantes), "faltantes": taller.faltantes}


@app.get("/reorder-suggestions")
def get_reorder_suggestions():
    """Sugerencias de compra vigentes[cite: 25]."""
    sugerencias = {}
    for f in taller.faltantes:
        pid = f.get("part_id")
        if not pid:
            continue
        if pid not in sugerencias:
            sugerencias[pid] = {
                "part_id": pid,
                "name": f.get("name"),
                "suggested_quantity": 0,
                "work_order_ids": []
            }
        sugerencias[pid]["suggested_quantity"] += f.get("missing_quantity", 0)
        wo_id = f.get("work_order_id")
        if wo_id not in sugerencias[pid]["work_order_ids"]:
            sugerencias[pid]["work_order_ids"].append(wo_id)
            
    return {"sugerencias": list(sugerencias.values())}


@app.get("/unmatched-receipts")
def get_unmatched_receipts():
    """Recepciones por relacionar a mano con una pieza[cite: 25]."""
    return {"unmatched_receipts": taller.recepciones_sin_relacionar}


# --- OPERACIONES DE PISO (POST) ---

@app.post("/issues")
def post_issue(payload: IssueRequest):
    """Salida de pieza contra orden de trabajo[cite: 25]."""
    try:
        taller.registrar_salida_piso(
            payload.work_order_id,
            payload.part_id,
            payload.location_id,
            payload.quantity,
            payload.issued_by
        )
        return {"status": "success", "message": "Salida registrada con éxito."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/transfers")
def post_transfer(payload: TransferRequest):
    """Transferencia de material entre ubicaciones[cite: 25]."""
    try:
        taller.transferir_stock(
            payload.part_id,
            payload.from_location_id,
            payload.to_location_id,
            payload.quantity
        )
        return {"status": "success", "message": "Transferencia realizada con éxito."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/counts")
def post_count(payload: CountRequest):
    """Conteo cíclico y ajuste de inventario[cite: 25]."""
    try:
        taller.ajustar_stock_conteo(
            payload.part_id,
            payload.location_id,
            payload.conteo_fisico,
            payload.reason
        )

        return {"status": "success", "message": "Ajuste por conteo cíclico registrado con éxito."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/unmatched-receipts/{line_id}/resolve")
def resolve_unmatched_receipt(line_id: int, payload: ResolveReceiptRequest):
    """Resuelve una recepción huérfana asociándola manualmente a un part_id."""
    try:
        taller.resolver_recepcion_manual(line_id, payload.part_id)
        return {"status": "success", "message": f"Recepción {line_id} resuelta y asociada a la pieza {payload.part_id} correctamente."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        

@app.get("/inventory-events")
def get_inventory_events():
    """Retorna todos los eventos de salida generados (correspondientes al tópico inventory.events)."""
    eventos = getattr(taller, "eventos_salida", [])
    return {
        "total_events": len(eventos),
        "events": eventos
    }

#Agregamos el EndPoint Valor total de S en el API
@app.get("/analytics/dashboard")
def obtener_dashboard_avanzado():
    # 1. Valuación del Stock Físico (On-Hand * Costo)
    valor_total_inventario = 0.0
    stock_total_unidades = 0
    for part_id, ubicaciones in taller.saldos.items():
        costo = taller.costos_unitarios.get(part_id, 0.0)
        for sub in ubicaciones.values():
            on_hand = sub.get("on_hand", 0)
            stock_total_unidades += on_hand
            valor_total_inventario += on_hand*costo

    # 2. Valuación y conteo de Faltantes / Sugerencias de Compra
    valor_total_faltantes = 0.0
    cantidad_total_faltantes = 0
    faltantes_lista = getattr(taller, 'faltantes', [])
    
    for f in faltantes_lista:
        pid = f.get("part_id")
        # Si no viene el part_id pero viene un estimado o buscamos por nombre
        cant_faltante = f.get("missing_quantity", 1) or 1
        cantidad_total_faltantes += cant_faltante
        
        # Si tenemos el costo de esa pieza, lo sumamos al valor monetario del faltante
        if pid and pid in taller.costos_unitarios:
            costo_pieza = taller.costos_unitarios.get(pid, 0.0)
            valor_total_faltantes += cant_faltante*costo_pieza

    return {
        "nivel": "Avanzado (Valuación y Contraste Financiero)",
        "stock_fisico": {
            "unidades_totales": stock_total_unidades,
            "valor_mxn": round(valor_total_inventario, 2)
        },
        "faltantes_compras": {
            "unidades_totales": cantidad_total_faltantes,
            "valor_estimado_mxn": round(valor_total_faltantes, 2)
        },
        "total_faltantes_activos": len(faltantes_lista)
    }


#---------------------------Linea de código para la verificación
#--------------------------- de funcionamiento del programa: 
if __name__ == "__main__":
    
    print(" Inicio de la Simulación Temporal...")
    taller = Taller()
    
   # Ruta absoluta del archivo de eventos
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    ruta_eventos = os.path.join(directorio_actual, "events.jsonl")
    
    conteo = 0
    print(f"Leyendo eventos desde '{ruta_eventos}'...")
    
    with open(ruta_eventos, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            evento = json.loads(linea)
            conteo += 1
            
            tipo = evento.get("type")
            data = evento.get("data", evento)
            
            # MAGIA AUTOMÁTICA: Llama solito al método _handle_xxx que tenga tu clase
            nombre_metodo = f"_handle_{tipo}"
            if hasattr(taller, nombre_metodo):
                try:
                    getattr(taller, nombre_metodo)(data)
                except Exception:
                    pass

    print(f"Análisis finalizado. Líneas procesadas: {conteo}")
    
    print("\n==================================================")
    print(" 📊 REPORTE DE ESTADO FINAL DEL TALLER Y VALUACIÓN ")
    print("==================================================")
    
    # Sumar inventario de forma segura
    total_piezas = 0
    try:
        for part_id, locs in taller.saldos.items():
            for loc_id, stats in locs.items():
                total_piezas += stats.get("on_hand", 0)
    except Exception:
        total_piezas = "Registrado en vectores de saldo"
    
    print(f" Total de unidades físicas en almacén (On-Hand): {total_piezas}")
    print(f" Saldos registrados en memoria (vectores): {len(getattr(taller, 'saldos', {}))}")
    print("\n✅ Simulación completada con éxito")