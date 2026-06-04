"use client";

import React from "react";

const beforeAfterResults = [
  { id: 1, procedure: "Rhinoplasty", description: "Dorsal hump reduction and tip refinement" },
  { id: 2, procedure: "Breast Augmentation", description: "325cc round silicone implants, submuscular" },
  { id: 3, procedure: "Facelift + Neck Lift", description: "Deep-plane technique with platysmaplasty" },
  { id: 4, procedure: "Liposuction", description: "VASER liposuction of abdomen and flanks" },
  { id: 5, procedure: "Blepharoplasty", description: "Upper and lower eyelid surgery" },
  { id: 6, procedure: "Tummy Tuck", description: "Full abdominoplasty with muscle repair" },
];

export default function ResultsSection() {
  return (
    <section id="results" className="py-20 bg-white">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <span className="inline-block px-4 py-1.5 rounded-full bg-accent/10 text-accent text-sm font-medium mb-4">
            Real Results
          </span>
          <h2 className="text-4xl md:text-5xl font-serif font-semibold text-primary mb-4">
            Before & After
          </h2>
          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            Every transformation is unique. These results showcase our commitment to natural, harmonious outcomes.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {beforeAfterResults.map((result) => (
            <div
              key={result.id}
              className="group bg-gray-50 rounded-2xl overflow-hidden border border-gray-100 hover:shadow-xl transition-all duration-300"
            >
              {/* Placeholder for Before/After Images */}
              <div className="relative h-64 bg-gradient-to-br from-gray-200 to-gray-300 flex items-center justify-center">
                <div className="text-center">
                  <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-white/80 mb-3">
                    <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                  </div>
                  <p className="text-sm text-gray-500 font-medium">Before / After</p>
                  <p className="text-xs text-gray-400 mt-1">Photos available in consultation</p>
                </div>
              </div>

              <div className="p-6">
                <h3 className="font-semibold text-xl text-primary mb-2">{result.procedure}</h3>
                <p className="text-gray-600 text-sm leading-relaxed">{result.description}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-12 text-center">
          <p className="text-sm text-gray-500 max-w-xl mx-auto">
            All patient photos are used with explicit consent. Individual results vary. A personal consultation is required to discuss your specific goals and expectations.
          </p>
        </div>
      </div>
    </section>
  );
}
