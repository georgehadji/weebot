import { credentials, aboutDetails } from "@/data";

export default function AboutSection() {
  return (
    <section id="about" className="section bg-white">
      <div className="max-w-7xl mx-auto px-6">
        {/* Section Header */}
        <div className="text-center mb-16">
          <span className="text-primary-500 font-medium text-sm tracking-widest uppercase">About the Surgeon</span>
          <h2 className="font-serif text-4xl sm:text-5xl font-bold text-neutral-900 mt-3 mb-4">
            Meet Dr. Jorgis Chatzivantsidis
          </h2>
          <div className="w-20 h-1 bg-gradient-to-r from-primary-500 to-accent-500 mx-auto rounded-full" />
        </div>

        <div className="grid lg:grid-cols-2 gap-16 items-center">
          {/* Photo */}
          <div className="relative">
            <div className="aspect-[4/5] rounded-2xl overflow-hidden bg-gradient-to-br from-neutral-100 to-neutral-200 shadow-2xl">
              <div className="w-full h-full flex items-center justify-center text-neutral-400">
                <div className="text-center">
                  <svg className="w-24 h-24 mx-auto mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                  <p className="text-sm">Surgeon Photo</p>
                </div>
              </div>
            </div>
            {/* Floating card */}
            <div className="absolute -bottom-6 -right-6 bg-white rounded-xl shadow-xl p-6 border border-neutral-100">
              <div className="text-3xl font-serif font-bold text-primary-600">15+</div>
              <div className="text-sm text-neutral-500">Years of Excellence</div>
            </div>
          </div>

          {/* Content */}
          <div>
            <h3 className="font-serif text-2xl font-semibold text-neutral-900 mb-6">
              Dedicated to Natural, Beautiful Results
            </h3>
            <div className="space-y-6">
              {aboutDetails.map((item) => (
                <div key={item.title}>
                  <h4 className="font-semibold text-neutral-800 mb-2">{item.title}</h4>
                  <p className="text-neutral-600 leading-relaxed">{item.text}</p>
                </div>
              ))}
            </div>

            {/* Credentials */}
            <div className="grid grid-cols-2 gap-4 mt-10">
              {credentials.map((cred) => (
                <div key={cred.label} className="bg-neutral-50 rounded-xl p-4 text-center">
                  <div className="font-serif text-xl font-bold text-primary-600">{cred.label}</div>
                  <div className="text-xs text-neutral-500 mt-1">{cred.detail}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
