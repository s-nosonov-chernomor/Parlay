from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db import par_dli_crud
from app.main_runtime import get_command_service
from app.services.bind_resolver import resolve_binding_topic


class ParDliEngineV2:

    def tick(self):
        with SessionLocal() as session:

            # 1. получаем сценарии
            scenarios = par_dli_crud.list_scenarios(session)

            for cfg in scenarios:

                # 2. все линии этого сценария
                ui_ids = par_dli_crud.list_ui_for_par(session, cfg.par_id)

                for ui_id in ui_ids:
                    self._process_line(session, cfg, ui_id)

            session.commit()

    def _process_line(self, session: Session, cfg, ui_id: str):
        svc = get_command_service()

        # resolve topics
        par_top_topic = resolve_binding_topic(session, ui_id, cfg.par_top_bind_key)
        par_sum_topic = resolve_binding_topic(session, ui_id, cfg.par_sum_bind_key)
        enabled_topic = resolve_binding_topic(session, ui_id, cfg.enabled_bind_key)
        dim_topic = resolve_binding_topic(session, ui_id, cfg.dim_bind_key)

        if not all([par_top_topic, par_sum_topic, enabled_topic, dim_topic]):
            return

        # 🔥 1. DLI расчет (по истории)
        now = datetime.now(timezone.utc)

        dli_raw, dli_capped = par_dli_crud.calc_dli_from_history(
            session=session,
            topic=par_sum_topic,
            start_ts=par_dli_crud.day_start(now),
            end_ts=now,
            cap_umol=cfg.dli_cap_umol,
        )

        current_dli = dli_capped if cfg.use_dli_cap else dli_raw

        # 🔥 2. ON/OFF
        enabled = 1
        if current_dli >= cfg.dli_target_mol:
            enabled = 0

        # 🔥 3. PWM (только текущее значение)
        par_top = par_dli_crud.get_last_value(session, par_top_topic)

        pwm = self._compute_pwm(par_top, cfg.ppfd_setpoint_umol, cfg.fixture_umol_100)

        # 🔥 отправка
        svc.send(session, svc.make_request(enabled_topic, enabled))
        svc.send(session, svc.make_request(dim_topic, pwm))

    def _compute_pwm(self, par_top, target, fixture):
        need = target - (par_top or 0)
        if need <= 0:
            return 0.0
        return min(100.0, need / fixture * 100.0)