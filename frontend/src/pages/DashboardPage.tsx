import {
  BarChart3,
  CalendarClock,
  CloudSun,
  Gauge,
  MapPin,
  ThermometerSun,
  UserRound
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, SkeletonGrid } from "../components/DataState";
import { MetricCard } from "../components/MetricCard";
import type { AnalyticsSummaryResponse, Metric, StationsResponse } from "../types";
import {
  biasSummary,
  defaultRange,
  formatDate,
  formatDateTime,
  formatNumber,
  isPrivilegedRole,
  metricLabels,
  roleLabel
} from "../utils";

interface DashboardData {
  summary: AnalyticsSummaryResponse | null;
  stations: StationsResponse | null;
}

const metricOrder: Metric[] = ["avg_temp", "min_temp", "max_temp", "precipitation"];

export function DashboardPage() {
  const { user } = useAuth();
  const [data, setData] = useState<DashboardData>({
    summary: null,
    stations: null
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const range = useMemo(() => defaultRange(30), []);
  const showRole = isPrivilegedRole(user?.role);

  useEffect(() => {
    let active = true;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [summary, stations] = await Promise.all([
          api.summary({ start_date: range.start, end_date: range.end, only_with_coordinates: true }),
          api.stations({ limit: 500 })
        ]);

        if (!active) {
          return;
        }

        setData({
          summary,
          stations
        });
      } catch (err) {
        if (active) {
          setError(formatApiError(err));
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [range.end, range.start]);

  const totalComparedPoints = metricOrder.reduce(
    (sum, metric) => sum + Number(data.summary?.metrics[metric]?.compared_points || 0),
    0
  );
  const activeMetricCount = metricOrder.filter((metric) => Number(data.summary?.metrics[metric]?.compared_points || 0) > 0).length;
  const avgTempMetric = data.summary?.metrics.avg_temp || null;
  const riskiestMetric =
    metricOrder
      .map((metric) => ({
        metric,
        max: data.summary?.metrics[metric]?.max_absolute_error ?? null
      }))
      .filter((item) => item.max !== null)
      .sort((left, right) => Number(right.max) - Number(left.max))[0] || null;
  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <span>Личный кабинет</span>
          <h1>{user?.full_name || "Пользователь"}</h1>
          <p>
            Рабочая сводка SkyCast за период {formatDate(range.start)} - {formatDate(range.end)}: как выглядит качество
            прогноза, где есть риск и куда перейти для детального разбора.
          </p>
        </div>
        <div className="headerActions">
          <Link className="ghostButton" to="/app/compare">
            <ThermometerSun size={18} />
            Разбор станции
          </Link>
          <Link className="primaryButton" to="/app/analytics">
            <BarChart3 size={18} />
            Открыть аналитику
          </Link>
        </div>
      </div>

      {loading ? <SkeletonGrid cards={4} /> : null}
      {error ? <ErrorState text={error} /> : null}

      {!loading && !error ? (
        <>
          <div className="metricGrid">
            <MetricCard icon={MapPin} label="Станций" value={formatNumber(data.stations?.total ?? 0)} tone="blue" />
            <MetricCard
              icon={Gauge}
              label="Сравнений"
              value={formatNumber(totalComparedPoints)}
              hint="по выбранному периоду"
              tone="green"
            />
            <MetricCard
              icon={ThermometerSun}
              label="Ошибка температуры"
              value={avgTempMetric?.mae === null || avgTempMetric?.mae === undefined ? "нет данных" : `${formatNumber(avgTempMetric.mae, 1)} °C`}
              hint={biasSummary(avgTempMetric?.bias, "avg_temp")}
              tone="amber"
            />
            <MetricCard
              icon={CloudSun}
              label="Погодных метрик"
              value={formatNumber(activeMetricCount)}
              hint="температура и осадки"
              tone="coral"
            />
          </div>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Профиль</span>
                <h2>Данные аккаунта</h2>
              </div>
              <UserRound size={20} />
            </div>
            <div className="detailGrid">
              <div>
                <span>Имя</span>
                <strong>{user?.full_name || "нет данных"}</strong>
              </div>
              <div>
                <span>Почта</span>
                <strong>{user?.email || "нет данных"}</strong>
              </div>
              {showRole ? (
                <div>
                  <span>Уровень доступа</span>
                  <strong>{roleLabel(user?.role)}</strong>
                </div>
              ) : null}
              <div>
                <span>Последний вход</span>
                <strong>{formatDateTime(user?.last_login_at)}</strong>
              </div>
              <div>
                <span>Аккаунт создан</span>
                <strong>{formatDateTime(user?.created_at)}</strong>
              </div>
              <div>
                <span>Статус</span>
                <strong>{user?.is_active ? "активен" : "отключен"}</strong>
              </div>
            </div>
          </article>

          <article className="panel">
            <div className="panelHeader">
              <div>
                <span>Главное</span>
                <h2>Короткие выводы по периоду</h2>
              </div>
              <CalendarClock size={20} />
            </div>
            <div className="detailGrid">
              <div>
                <span>Наиболее рискованная метрика</span>
                <strong>{riskiestMetric ? metricLabels[riskiestMetric.metric] : "нет данных"}</strong>
              </div>
              <div>
                <span>Максимальный промах</span>
                <strong>
                  {riskiestMetric?.max === null || riskiestMetric?.max === undefined
                    ? "нет данных"
                    : `${formatNumber(riskiestMetric.max, 1)} ${riskiestMetric.metric === "precipitation" ? "мм" : "°C"}`}
                </strong>
              </div>
              <div>
                <span>Смещение по температуре</span>
                <strong>{biasSummary(avgTempMetric?.bias, "avg_temp")}</strong>
              </div>
              <div>
                <span>Сравнений по температуре</span>
                <strong>{formatNumber(avgTempMetric?.compared_points ?? 0)}</strong>
              </div>
            </div>
          </article>

          <div className="quickGrid">
            <Link className="quickTile" to="/app/analytics">
              <BarChart3 size={22} />
              <strong>Полный анализ периода</strong>
              <span>Запустите разбор по датам, метрике и станции по кнопке.</span>
            </Link>
            <Link className="quickTile" to="/app/compare">
              <ThermometerSun size={22} />
              <strong>Разбор одной станции</strong>
              <span>Посмотрите ежедневный факт, прогноз и ошибку без ручного сопоставления строк.</span>
            </Link>
            <Link className="quickTile" to="/app/forecasts">
              <CloudSun size={22} />
              <strong>Прогнозы по станции</strong>
              <span>Посмотрите прогнозные значения за выбранный период.</span>
            </Link>
          </div>

        </>
      ) : null}
    </section>
  );
}
