# async def get_tracker_status(self, uid: str, phone_number: Optional[str] = None) -> Optional[str]:
#         print(f"Работаю с UID={uid}")
#
#         # Получаем значения заголовков
#         token, device_id, ua = self._header_values()
#
#         # Проверяем, если есть телефон в кэше, используем его shard
#         shard = None
#         if phone_number and phone_number in self.cache:
#             shard = self.cache[phone_number]
#             print(f"Используем закэшированный shard={shard} для phone_number={phone_number}")
#
#         # Если shard не найден в кэше, начинаем пробовать от 1 до 100
#         if not shard:
#             print("Не найден подходящий shard в кэше, пробую все от 1 до 100.")
#             for shard in range(1, 101):
#                 print(f"Делаю запрос с shard={shard}")
#                 url = f"https://wbx-status-tracker.wildberries.ru/api/v3/statuses/{uid}?shard={shard}"
#                 fetch_js = f"""
#                     const response = await fetch('{url}', {{
#                         method: 'GET',
#                         headers: {{
#                             'Accept': 'application/json',
#                             'Content-Type': 'application/json',
#                             'Authorization': 'Bearer {token}',
#                             'DeviceId': '{device_id}',
#                             'User-Agent': '{ua}'
#                         }},
#                         credentials: 'include'
#                     }});
#
#                     return {{
#                         status: response.status,
#                         ok: response.ok,
#                         text: await response.text()
#                     }};
#                 """
#
#                 res = await self._evaluate_fetch_js(fetch_js)
#                 print(res)
#                 # Проверка ответа
#                 if res and isinstance(res, dict) and res.get("status") == 200:
#                     print(f"Ответ от API с shard={shard} - статус 200")
#                     if phone_number:
#                         self.cache[phone_number] = shard  # Кэшируем найденный shard для phone_number
#                         self.save_cache()  # Сохраняем кэш в файл
#                     break
#                 else:
#                     print(f"shard={shard} не подошел. Статус: {res.get('status') if res else 'No response'}")
#
#         # Теперь выполняем основной запрос с найденным shard
#         if shard:
#             url = f"https://wbx-status-tracker.wildberries.ru/api/v3/statuses/{uid}?shard={shard}"
#             fetch_js = f"""
#                 const response = await fetch('{url}', {{
#                     method: 'GET',
#                     headers: {{
#                         'Accept': 'application/json',
#                         'Content-Type': 'application/json',
#                         'Authorization': 'Bearer {token}',
#                         'DeviceId': '{device_id}',
#                         'User-Agent': '{ua}'
#                     }},
#                     credentials: 'include'
#                 }});
#
#                 return {{
#                     status: response.status,
#                     ok: response.ok,
#                     text: await response.text()
#                 }};
#             """
#
#             res = await self._evaluate_fetch_js(fetch_js)
#
#             if res and isinstance(res, dict) and res.get("status") == 200:
#                 try:
#                     statuses = json.loads(res.get('text', '{}'))
#                     last_status = statuses[-1] if statuses else None
#
#                     if last_status:
#                         if uid == last_status.get('rid'):
#                             print(f"Последний статус для UID={uid}: {last_status['status_name']}")
#                             return last_status['status_name']
#                         else:
#                             print(f"UID не совпадает с rid: {uid} != {last_status.get('rid')}")
#                     else:
#                         print(f"Статусов не найдено для UID={uid}")
#                 except json.JSONDecodeError:
#                     print(f"Ошибка декодирования JSON для UID={uid}")
#             else:
#                 print(
#                     f"[TRACKER] Не получилось взять статус для UID={uid}. Статус API: {res.get('status') if res else 'No response'} Текст: {res.get('text') if res else 'No response text'}")
#
#         else:
#             print("Не удалось найти подходящий shard.")
#
#         return None