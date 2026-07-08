import { Activity, ArrowRight, BarChart3, CheckCircle2, CloudSun, Gauge, MapPin, PlayCircle, ShieldCheck, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";

const features = [
  {
    icon: CloudSun,
    title: "Прогноз и реальная погода рядом",
    text: "Выберите город и период, чтобы увидеть прогноз и фактическую погоду в одном месте."
  },
  {
    icon: Gauge,
    title: "Понятная оценка точности",
    text: "Сервис показывает, насколько прогноз совпал с фактом, без сложных расчетов на экране."
  },
  {
    icon: ShieldCheck,
    title: "Разные уровни доступа",
    text: "Каждый человек видит только те разделы, которые нужны ему для работы."
  },
  {
    icon: BarChart3,
    title: "Графики без перегруза",
    text: "Ошибки, совпадения и динамика собраны в аккуратные карточки и таблицы."
  }
];

export function LandingPage() {
  return (
    <main className="landing">
      <section className="hero">
        <img className="heroImage" src="/skycast-hero.png" alt="" />
        <div className="heroOverlay" />
        <div className="heroContent">
          <div className="heroCopy">
            <h1>SkyCast</h1>
            <p>Сервис сравнивает прогноз погоды с фактической погодой и сразу показывает, насколько прогнозу можно доверять.</p>
            <div className="heroActions">
              <Link className="primaryButton" to="/register">
                Начать пользоваться
                <ArrowRight size={18} />
              </Link>
              <a className="ghostButton" href="#how">
                Как это работает
                <PlayCircle size={18} />
              </a>
            </div>
            <div className="heroChecks">
              <span>
                <CheckCircle2 size={17} /> Понятные графики
              </span>
              <span>
                <CheckCircle2 size={17} /> Русский интерфейс
              </span>
              <span>
                <CheckCircle2 size={17} /> Быстрый выбор данных
              </span>
            </div>
          </div>

          <aside className="weatherGlass" aria-label="Пример аналитической карточки">
            <div className="glassHeader">
              <div>
                <span>Москва</span>
                <strong>Точность прогноза</strong>
              </div>
              <div className="glassIcon">
                <TrendingUp size={19} />
              </div>
            </div>
            <div className="glassMetricRow">
              <div className="matchRing" aria-label="Совпадение 92 процента">
                <strong>92%</strong>
                <span>совпадение</span>
              </div>
              <div className="glassFacts">
                <div>
                  <CloudSun size={18} />
                  <span>Прогноз</span>
                  <strong>18 °C</strong>
                </div>
                <div>
                  <MapPin size={18} />
                  <span>Факт</span>
                  <strong>17 °C</strong>
                </div>
              </div>
            </div>
            <div className="glassChart" aria-hidden="true">
              {[42, 68, 56, 82, 74, 90, 78].map((height, index) => (
                <span key={index} style={{ height: `${height}%` }} />
              ))}
            </div>
            <div className="glassFooter">
              <span>
                <Activity size={16} /> Средняя разница
              </span>
              <strong>1°C</strong>
            </div>
          </aside>
        </div>
      </section>

      <section className="featureBand" id="features">
        <div className="sectionHeader">
          <span>Платформа</span>
          <h2>Почему выбирают SkyCast?</h2>
        </div>
        <div className="featureGrid">
          {features.map(({ icon: Icon, title, text }) => (
            <article className="featureCard" key={title}>
              <div className="featureIcon">
                <Icon size={24} />
              </div>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="howBand" id="how">
        <div className="sectionHeader">
          <span>Порядок работы</span>
          <h2>Как это работает</h2>
        </div>
        <div className="timeline">
          <article>
            <MapPin size={23} />
            <strong>1. Выберите город</strong>
            <p>Начните с нужной станции или населенного пункта.</p>
          </article>
          <article>
            <CloudSun size={23} />
            <strong>2. Укажите период</strong>
            <p>Выберите даты, за которые хотите проверить погоду.</p>
          </article>
          <article>
            <BarChart3 size={23} />
            <strong>3. Получите результат</strong>
            <p>Смотрите прогноз, факт и разницу в понятных карточках.</p>
          </article>
        </div>
      </section>

      <section className="contactBand">
        <div>
          <span>Готово к работе</span>
          <h2>Откройте кабинет и посмотрите прогноз рядом с фактической погодой.</h2>
        </div>
        <Link className="primaryButton" to="/login">
          Открыть кабинет
          <ArrowRight size={18} />
        </Link>
      </section>
    </main>
  );
}
