import React, { Component } from 'react';
import logo from './logo.svg';
import './App.css';

class App extends Component {
  constructor(props) {
    super();

    // state of the user interaction.
    // the 'page' is critical, it decides what page we're displaying, via
    // a switch statement in render().
    this.state = {
        page: "chooseLang",
        lang: "en",
        town: "iqaluit",
        power: {}
    };

    // static data, never changes
    this.data = {
        power: {
            // capacity in [0,1], nameplate in kW, name in english (todo: xlate)
            slr: { cap: 0.15, nameplate: 1, price: 400, name: "solar panel" },
            smw: { cap: 0.29, nameplate: 100, price: 100000, name: "small wind tower" },
            lgw: { cap: 0.29, nameplate: 2300, price: 2e6, name: "large wind tower" },
            die: { cap: 0.80, nameplate: 100, price: 70000, name: "diesel generator" },
        },
    };

    this.setLanguageEn = this.setLanguage.bind(this, "en");
    this.setLanguageFr = this.setLanguage.bind(this, "fr");
    this.setLanguageIu = this.setLanguage.bind(this, "iu");
    this.setTownIqaluit = this.setTown.bind(this, "iqaluit");
    this.setTownRankinInlet = this.setTown.bind(this, "rankininlet");
    this.updatePower = this.updatePower.bind(this);
    this.render = this.render.bind(this);
  }

  getTownDemand() {
    return 8000;
  }

  setLanguage(languageName) {
    this.setState({...this.state, lang: languageName, page: "chooseLoc"});
  }

  setTown(townName) {
    this.setState({...this.state, town: townName, page: "choosePower"});
  }

  updatePower(event) {
    var newPower = {...this.state.power};
    newPower[event.target.name] = event.target.value;

    var newState = {...this.state, page: "choosePower",
        power: newPower
    };
    this.setState(newState);
  }

  renderChooseLanguage()
  {
     return (
        <div>
        <div><a href="#" onClick={this.setLanguageEn}>English</a></div>
        <div><a href="#" onClick={this.setLanguageFr}>Francais</a></div>
        <div><a href="#" onClick={this.setLanguageIu}>Inuktitut</a></div>
        </div>
     );
  }

  renderChooseLocation()
  {
    return (
        <div>
        <div><a href="#" onClick={this.setTownIqaluit}>Iqaluit</a></div>
        <div><a href="#" onClick={this.setTownRankinInlet}>Rankin Inlet</a></div>
        </div>
    );
  }

  renderPowerSupply() {
      // calculate whether we have any power at all
      var installed = this.state.power;
      var data = this.data.power;
      var demand = this.getTownDemand();
      var nameplate = 0;
      var generated = 0;
      var price = 0;
      // eslint-disable-next-line
      for(var typ in installed) {
          var numUnits = installed[typ];
          var typeData = data[typ];
          nameplate += numUnits * typeData.nameplate;
          generated += numUnits * typeData.nameplate * typeData.cap;
          price += numUnits * typeData.price;
      }
      if (nameplate === 0) {
          // no power installed => don't print out the data!
          return (<div>
                You need to generate {demand} kW of power.
          </div>);
      }
      var actuallyProduced = (<div>
              Total nameplate capacity: {nameplate.toFixed()} kW.<br/>
              Actual generation: {generated.toFixed()} kW.<br/>
              Capital cost: $ {price.toFixed()}.<br/>
              </div>);

      var result = "";
      if (generated < demand) {
        result = (<div>You need to produce {demand.toFixed()} kW.
                        You are short by {(demand - generated).toFixed()} kW.</div>);
      } else {
        result = (<div>Congrats, you're producing enough power! Can you do it for cheaper?</div>);
      }

      return (
        <div>
          {actuallyProduced}
          <br/>
          <br/>
          {result}
        </div>);
  }

  renderInput(name) {
      var plant = this.data.power[name];
      return (
              <div>
              {plant.name}
              <input type="number" onChange={this.updatePower} name={name}/>
              { plant.nameplate + " kW each, capacity factor " + 
              (plant.cap * 100).toFixed() + "%, $ " + plant.price}
              <br/>
              </div>
             );
  }

  renderChoosePower()
  {
    return (
        <div>
        <form id="choose-power-form">
            {this.renderInput("slr")}
            {this.renderInput("smw")}
            {this.renderInput("lgw")}
            {this.renderInput("die")}
        </form>
        <br/>
        {this.renderPowerSupply()}
        </div>
    );
  }

  renderInternal() {
      if(this.state.page === "chooseLang") {
        return this.renderChooseLanguage();
      } else if (this.state.page === "chooseLoc") {
        return this.renderChooseLocation();
      } else if (this.state.page === "choosePower") {
        return this.renderChoosePower();
      }
  }

  render() {
    return (
      <div className="App">
        <div className="App-header">
          <img src={logo} className="App-logo" alt="logo" />
          <h2>Welcome to React</h2>
        </div>
        {this.renderInternal()}
        <p className="App-intro">
                State now: {JSON.stringify(this.state)}
        </p>
      </div>
    );
  }
}

export default App;
