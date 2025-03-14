import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger


class AutomationHandler:
    def __init__(
        self,
        api_client,
        mqtt_handler,
        virtual_thermostat,
        physical_device,
        weather_client,
        presets,
    ):
        self.logger = logging.getLogger("Yutampo_ha_addon")
        self.api_client = api_client
        self.mqtt_handler = mqtt_handler
        self.virtual_thermostat = virtual_thermostat
        self.physical_device = physical_device
        self.weather_client = weather_client
        self.scheduler = BackgroundScheduler()
        self.presets = presets  # Liste des préréglages personnalisés
        self.season_preset = self.presets[0]["name"]  # Premier préréglage par défaut
        self.heating_duration = self.presets[0]["duration"]  # Durée initiale

    def start(self):
        """Démarre l'automation interne."""
        self._schedule_automation()
        self.scheduler.start()
        self.logger.info("Automation interne démarrée.")

    def _schedule_automation(self):
        """Planifie l'exécution de l'automation toutes les 5 minutes."""
        self.scheduler.add_job(
            self._run_automation,
            trigger=IntervalTrigger(minutes=5),
            next_run_time=datetime.now() + timedelta(seconds=5),
        )

    def _run_automation(self):
        """Exécute la logique de contrôle graduel."""
        self.logger.debug("Exécution de l'automation interne...")
        hottest_hour = self.weather_client.get_hottest_hour()
        start_hour = hottest_hour - (self.heating_duration / 2)
        end_hour = hottest_hour + (self.heating_duration / 2)

        current_time = datetime.now()
        current_hour = current_time.hour + current_time.minute / 60.0

        # Ajuster les heures pour gérer les transitions de minuit
        if start_hour < 0:
            start_hour += 24
        if end_hour >= 24:
            end_hour -= 24

        c = self.virtual_thermostat.target_temperature
        a = (
            self.virtual_thermostat.target_temperature_high
            - self.virtual_thermostat.target_temperature_low
        ) / 2

        if (current_hour >= start_hour and current_hour < end_hour) or (
            start_hour > end_hour
            and (current_hour >= start_hour or current_hour < end_hour)
        ):
            # Calculer la progression dans la plage de variation
            if current_hour >= start_hour:
                progress = (current_hour - start_hour) / self.heating_duration
            else:
                progress = (current_hour + 24 - start_hour) / self.heating_duration
            target_temp = c - a + 2 * a * progress
        else:
            target_temp = c - a  # En dehors de la plage, utiliser le point bas

        target_temp = round(target_temp, 1)
        self.logger.debug(f"Consigne calculée pour le Yutampo : {target_temp}°C")

        # Appliquer la consigne au Yutampo physique
        if self.api_client.set_heat_setting(
            self.physical_device.parent_id, setting_temp_dhw=target_temp
        ):
            self.physical_device.setting_temperature = target_temp
            self.mqtt_handler.publish_state(
                self.physical_device.id,
                self.physical_device.setting_temperature,
                self.physical_device.current_temperature,
                self.physical_device.mode,
                self.physical_device.action,
                self.physical_device.operation_label,
            )
        else:
            self.logger.error(
                "Échec de l'application de la consigne au Yutampo physique."
            )

    def set_season_preset(self, preset_name):
        """Met à jour le préréglage saisonnier et applique les paramètres correspondants."""
        for preset in self.presets:
            if preset["name"] == preset_name:
                self.season_preset = preset_name
                self.heating_duration = preset["duration"]
                self.virtual_thermostat.set_temperature(preset["target_temperature"])
                self.virtual_thermostat.set_temperature_low(
                    preset["target_temperature_low"]
                )
                self.virtual_thermostat.set_temperature_high(
                    preset["target_temperature_high"]
                )
                self.logger.info(
                    f"Préréglage saisonnier mis à jour : {self.season_preset}, durée de variation : {self.heating_duration} heures"
                )
                return
        self.logger.warning(f"Préréglage inconnu : {preset_name}")
