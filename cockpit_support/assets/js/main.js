var _working_mode = "production"; // modes:  dev production

var _tab_name = "support";
var global_path = "/usr/local/share/dlbt_os/gen/"
var py_path = "/usr/local/share/dlbt_os/cockpit_support/py_backend/"

function init(){
    var hr = "https://www.notion.so/bizonbizon/Bizon-Technical-Support-Portal-b2e41329576c49a081ea1617dfd9a8c7";
    var btn = document.getElementById("see-guides");
    btn.setAttribute("type", "button");
    btn.setAttribute("href", hr);
    btn.setAttribute("target", "_blank");
}


let stateCheck1 = setInterval(() => {
    console.log("here tho")
    if (document.readyState === 'complete') {
        clearInterval(stateCheck1);
        init();   
    }
}, 100);