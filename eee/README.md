# EEE Career Masterbook — Blogger Setup

## কোন file ব্যবহার করবেন

- `eee-career-masterbook-self-contained.html` — Blogger-এর জন্য সরাসরি ব্যবহারযোগ্য একক file।
- `eee-career-masterbook-blogger.html` — একই Blogger-safe layout-এর standard build।
- `blogger-embed-loader.html` — **সবচেয়ে ভালো সমাধান**। ছোট (~১ KB) iframe loader যা GitHub CDN থেকে পুরো বই load করে।

## Blogger-এ যোগ করার নিয়ম (সবচেয়ে সহজ — iframe loader)

**সমস্যা:** `eee-career-masterbook-blogger.html`-এর সাইজ ৩.৬ MB, কিন্তু Blogger-এর HTML/JavaScript gadget-এর body limit প্রায় ১ MB। তাই সরাসরি paste করলে **"body is too large"** error আসে।

**সমাধান:** `blogger-embed-loader.html`-এর ছোট কোড (~১ KB) ব্যবহার করুন। এটি GitHub CDN থেকে পুরো বই iframe-এ load করবে।

1. আগে Blogger theme-এর backup নিন।
2. **Layout → Add a Gadget → HTML/JavaScript** খুলুন।
3. `blogger-embed-loader.html`-এর পুরো কোড copy করে paste করুন।
4. কোডের ভেতরে `YOUR_USERNAME` ও `YOUR_REPO`-এর জায়গায় আপনার GitHub username ও repository name বসান।
5. Gadget-টি book content-এর নিচে এমন জায়গায় রাখুন যেখানে full width পাওয়া যায়।

> **নোট:** GitHub-এ push করার পর jsDelivr CDN-এ content পৌঁছাতে ৫–১০ মিনিট লাগতে পারে। প্রথমবার load-এর সময় একটু অপেক্ষা করতে হবে।

## বিকল্প: সরাসরি HTML paste (যদি সাইজ কমাতে হয়)

1. আগে Blogger theme-এর backup নিন।
2. **Layout → Add a Gadget → HTML/JavaScript** খুলুন।
3. Self-contained HTML file-এর পুরো code paste করুন।
4. Gadget-টি book content-এর নিচে এমন জায়গায় রাখুন যেখানে full width পাওয়া যায়।
5. Blogger post editor script বাদ দিলে post-এর ভিতরে না দিয়ে HTML/JavaScript gadget অথবা Theme HTML ব্যবহার করুন।

## নতুন chapter যোগ করা

বর্তমান naming convention অনুসারে নতুন chapter folder ও ছয়টি Markdown file যোগ করুন। তারপর চালান:

```text
node blogger-web/build-blogger.mjs
```

Build script নিজে থেকেই সব `NN_Volume_* / Chapter-NN_*` folder খুঁজে chapter menu, content, MCQ, Viva, Glossary, Videos ও References যোগ করবে। Frontend code আলাদাভাবে edit করতে হবে না।

## বর্তমান layout

- আলাদা header বা footer নেই।
- সবার উপরে মোট chapter ও topic-এর automatic count, তারপর search এবং expandable chapter list।
- প্রতিটি chapter-এর মধ্যে Short Question & Answer, MCQ Quiz Test এবং Viva Preparation রয়েছে।
- Short Question অংশে প্রতিটি topic প্রশ্ন হিসেবে expand হয়; প্রথম প্রশ্নটি শুরুতেই খোলা থাকে।
- Desktop-এ search chapter panel-এর ওপরে থাকে। Mobile-এ প্রথমে শুধু content দেখা যায়; "Chapters" button চাপলে বাম দিক থেকে chapter/search sidebar খোলে।
- Mobile-এর chapter switch bar sticky, তাই content scroll করলেও switch করার button হারায় না।
- Search Results শুধু search field-এ কিছু লিখলে দেখা যায়; default অবস্থায় আলাদা result section থাকে না।
- Chapter 01-এর ছয়টি Short Question card-এ topic-specific optimized educational image রয়েছে; self-contained file-এ images embed করা।
- Standard build-এর Chapter 01 images `assets/chapter-01-introduction-to-electricity/` folder-এ রাখা হয়েছে। ভবিষ্যৎ chapter-এর images-ও একইভাবে নিজস্ব chapter folder-এ রাখতে হবে।
- MCQ Quiz Test-এ correct option সবুজ এবং ভুল selected option লাল হয়। Correct, Wrong ও Answered/Total live score chapter অনুযায়ী সংরক্ষিত থাকে; Reset Quiz দিয়ে আবার শুরু করা যায়।
- `English | বাংলা` switch রয়েছে। বাংলা mode-এ interface labels এবং ১২টি Short Question-এর author-reviewed বিস্তারিত বাংলা explanation দেখা যায়। প্রতিটি topic-এ সহজ ধারণা, বাস্তব উদাহরণ ও মনে রাখার মূল কথা রয়েছে; internationally accepted technical terms ও মূল English answer পাশাপাশি রাখা হয়। Language preference browser-এ সংরক্ষিত থাকে।
- Desktop-এ ডান পাশের panel-এ এবং mobile-এ chapter list-এর নিচে selected content দেখা যায়।

## Blogger theme conflict protection

সব CSS selector `#eee-masterbook` container-এর মধ্যে সীমাবদ্ধ। কোনো global `body`, `h1`, `a`, `button` বা Blogger theme class পরিবর্তন করা হয়নি।