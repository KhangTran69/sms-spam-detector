/*
 * Curated from tracked synthetic PH fixtures:
 *   - data/raw/ph_supplement_4.csv (spam)
 *   - data/raw/ph_supplement_5.csv (ham)
 * These are training examples, not real inbox messages or evaluation evidence.
 * Links use only the reserved example.com domain and sensitive values stay masked.
 */
export const EXAMPLES = {
  scam: [
    "SampleBank alert: your access will be blocked today. Send [CODE] at example.com/bank to keep the account open.",
    "SampleBank kuno ito: na-freeze ang online access mo. I-check daw sa example.com/bank bago mag-24 oras.",
    "May problema raw sa SampleBank profile. Ipadala ang [CODE] sa review page: example.com/bank para maibalik ang access.",
    "Delivery notice: the parcel is held until the [AMOUNT] release charge is paid at example.com/parcel.",
    "Naka-hold daw ang package mo. Bayaran ang [AMOUNT] sa example.com/parcel para ma-reschedule ang delivery.",
    "Hindi raw maihatid ang padala dahil kulang ang address. Magbayad ng [AMOUNT] sa example.com/parcel.",
    "Congrats! You were picked for a reward. Pay [AMOUNT] at example.com/reward to release your prize today.",
    "Napili raw ang number mo sa raffle. I-claim ang premyo matapos magbayad ng [AMOUNT] sa example.com/reward.",
    "May napanalunan ka raw na papremyo. Ipadala ang [ACCOUNT] at bayad na [AMOUNT] sa example.com/reward.",
    "Remote rating work pays [AMOUNT] per day. Send an enrollment deposit at example.com/work to reserve your slot.",
    "WFH daw, malaking kita kahit walang experience. Magbayad muna ng [AMOUNT] sa example.com/work para makapagsimula.",
    "May trabahong online na mataas ang sahod. Ipadala ang [AMOUNT] na registration fee sa example.com/work.",
    "A [AMOUNT] loan is pre-approved with no checks. Pay the release fee at example.com/loan before funds are sent.",
    "Approved na raw ang loan mo kahit walang requirements. I-release ang [AMOUNT] fee sa example.com/loan.",
    "May pautang daw na agarang makukuha. Bayaran muna ang processing fee na [AMOUNT] sa example.com/loan.",
    "Join today and earn fixed daily returns! Send [AMOUNT] at example.com/invest to activate your spot.",
    "Guaranteed daw ang kita kada araw. Magpasok ng [AMOUNT] sa example.com/invest para ma-activate ang account.",
    "Sigurado raw ang tubo sa loob ng isang linggo. Ipadala ang [AMOUNT] sa example.com/invest para sumali.",
    "This is the school office. A student account has an urgent unpaid balance. Settle [AMOUNT] at example.com/notice.",
    "School office daw ito. May bayarin kuno na dapat ayusin ngayon; bayaran ang [AMOUNT] sa example.com/notice.",
  ],
  safe: [
    "Your SampleApp sign-in code is [CODE]. It expires soon. We will never ask you to share it.",
    "Code mo sa SampleApp: [CODE]. Ikaw lang ang dapat gumamit nito.",
    "Ang iyong code sa SampleApp ay [CODE]. Huwag itong ibahagi kaninuman.",
    "SampleBank: Your card purchase of [AMOUNT] was approved. If this was not you, call the number on your card.",
    "SampleBank alert: may transaction kang [AMOUNT]. Check mo sa official app kung hindi ikaw iyon.",
    "SampleBank: May transaksiyong [AMOUNT] sa card mo. Tingnan sa opisyal na app kung hindi ikaw iyon.",
    "Your parcel is out for delivery today. Track order [ORDER] in the SampleApp or at example.com/track.",
    "Out for delivery na ang order [ORDER]. Check mo sa app o example.com/track para sa update.",
    "Ihahatid ngayong araw ang order [ORDER]. Tingnan ang update sa app o example.com/track.",
    "Your Sample Utility bill of [AMOUNT] is due on [DATE]. View your statement in the official app.",
    "Due na sa [DATE] ang bill mong [AMOUNT]. Makikita ang statement sa official app.",
    "Due sa [DATE] ang bayarin mong [AMOUNT]. Tingnan ang statement sa opisyal na app.",
    "This weekend only: 10% off selected items at SampleShop. See store details at example.com/deals.",
    "May 10% off sa piling items this weekend sa SampleShop. Details: example.com/deals",
    "May diskuwento sa piling produkto ngayong weekend sa SampleShop. Detalye: example.com/deals",
    "Reminder: the class project is due Friday. Please upload your file to the school portal.",
    "Reminder lang, due Friday ang project natin. Upload sa school portal pag ready na.",
    "Paalala: Biyernes ang pasahan ng proyekto. I-upload ito sa portal ng paaralan.",
    "Hi team, the meeting moved to 10AM. Please bring the updated sales report.",
    "Good day parents! Walang pasok sa 10AM dahil sa bagyo. Stay safe po.",
  ],
};
