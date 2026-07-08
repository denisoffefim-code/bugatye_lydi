import { ArrowRight, BarChart3, Bell, CheckCircle2, CloudSun, DatabaseZap, PlayCircle, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

const features = [
  {
    icon: CloudSun,
    title: "Прогнозы и факт",
    text: "Сравнивайте прогнозы, станции и фактические наблюдения в одном интерфейсе."
  },
  {
    icon: BarChart3,
    title: "Аналитика ошибок",
    text: "Оценивайте среднюю ошибку, отклонения и проблемные станции за выбранный период."
  },
  {
    icon: ShieldCheck,
    title: "RBAC-доступ",
    text: "Роли доступа помогают разделять просмотр, аналитику и администрирование."
  },
  {
    icon: DatabaseZap,
    title: "Надежные источники",
    text: "Интерфейс работает с реальными источниками и не подмешивает клиентские данные."
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
            <h1>
              Точный прогноз. Реальная погода. <span>Умный анализ.</span>
            </h1>
            <p>SkyCast сравнивает прогнозы с наблюдениями и показывает, каким данным можно доверять.</p>
            <div className="heroActions">
              <Link className="primaryButton" to="/register">
                Начать бесплатно
                <ArrowRight size={18} />
              </Link>
              <a className="ghostButton" href="#how">
                Как это работает
                <PlayCircle size={18} />
              </a>
            </div>
            <div className="heroChecks">
              <span>
                <CheckCircle2 size={17} /> Живые данные
              </span>
              <span>
                <CheckCircle2 size={17} /> Защищенные страницы
              </span>
              <span>
                <CheckCircle2 size={17} /> Адаптивный UI
              </span>
            </div>
          </div>

          <aside className="weatherGlass" aria-label="Пример аналитической карточки">
            <div className="glassHeader">
              <strong>Москва, Россия</strong>
              <span>Пример карточки</span>
            </div>
            <div className="glassGrid">
              <div>
                <small>Прогноз</small>
                <strong>18°C</strong>
                <span>Облачность</span>
              </div>
              <div>
                <small>Факт</small>
                <strong>17°C</strong>
                <span>Наблюдение</span>
              </div>
            </div>
            <div className="accuracyLine">
              <span />
            </div>
            <div className="glassFooter">
              <span>Ошибка температуры</span>
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
          <span>Поток данных</span>
          <h2>Как это работает</h2>
        </div>
        <div className="timeline">
          <article>
            <CloudSun size={23} />
            <strong>1. Загрузка прогнозов</strong>
            <p>Backend сохраняет forecast runs и значения по станциям.</p>
          </article>
          <article>
            <Bell size={23} />
            <strong>2. Прием факта</strong>
            <p>Telemetry endpoint пишет наблюдения в operational store.</p>
          </article>
          <article>
            <BarChart3 size={23} />
            <strong>3. Аналитика</strong>
            <p>Read models считают ошибки и рейтинги для интерфейса.</p>
          </article>
        </div>
      </section>

      <section className="contactBand" id="contacts">
        <div>
          <span>Готово к работе</span>
          <h2>Перейдите в кабинет и подключитесь к данным backend.</h2>
        </div>
        <Link className="primaryButton" to="/login">
          Открыть кабинет
          <ArrowRight size={18} />
        </Link>
      </section>
    </main>
  );
}
