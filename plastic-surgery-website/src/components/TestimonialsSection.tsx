"use client";

import React from "react";

const testimonials = [
  { id: 1, name: "Maria K.", procedure: "Rhinoplasty", text: "Dr. Chatzivantsidis completely transformed my confidence. The results look so natural that no one can tell I had surgery.", rating: 5 },
  { id: 2, name: "Eleni P.", procedure: "Breast Augmentation", text: "From the first consultation to the final follow-up, the experience was exceptional. Dr. Chatzivantsidis listened carefully to what I wanted.", rating: 5 },
  { id: 3, name: "Nikos A.", procedure: "Liposuction", text: "I was nervous about the procedure, but the team made me feel completely at ease. The results are exactly what I hoped for.", rating: 5 },
  { id: 4, name: "Sophia M.", procedure: "Facelift", text: "At 55, I wanted to look refreshed, not different. Dr. Chatzivantsidis understood perfectly. I look like myself, just 10 years younger.", rating: 5 },
  { id: 5, name: "Dimitris T.", procedure: "Blepharoplasty", text: "The tired look I had for years is gone. Friends keep asking if I have been on vacation. The recovery was quick and the results are fantastic.", rating: 5 },
];

export default function TestimonialsSection() {
  return (
    <section id="testimonials" className="py-20 bg-gray-50">
      <div className="max-w-7xl mx-auto px-6">
        <div className="text-center mb-16">
          <span className="inline-block px-4 py-1.5 rounded-full bg-primary/10 text-primary text-sm font-medium mb-4">
            Patient Stories
          </span>
          <h2 className="text-4xl md:text-5xl font-serif font-semibold text-primary mb-4">
            What Our Patients Say
          </h2>
          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            Real experiences from real patients who trusted us with their transformation.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {testimonials.map((testimonial) => (
            <div
              key={testimonial.id}
              className="bg-white rounded-2xl p-8 shadow-sm border border-gray-100 hover:shadow-lg transition-all duration-300 flex flex-col"
            >
              {/* Stars */}
              <div className="flex gap-1 mb-4">
                {Array.from({ length: testimonial.rating }).map((_, i) => (
                  <svg key={i} className="w-5 h-5 text-yellow-400" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                  </svg>
                ))}
              </div>

              <blockquote className="text-gray-700 leading-relaxed flex-grow mb-6">
                &ldquo;{testimonial.text}&rdquo;
              </blockquote>

              <div className="pt-4 border-t border-gray-100">
                <p className="font-semibold text-primary">{testimonial.name}</p>
                <p className="text-sm text-gray-500">{testimonial.procedure}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-12 text-center">
          <p className="text-sm text-gray-500">
            * Testimonials are genuine patient experiences. Results and experiences vary by individual.
          </p>
        </div>
      </div>
    </section>
  );
}
